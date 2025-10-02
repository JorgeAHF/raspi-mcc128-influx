"""Configuration endpoints exposing typed schemas."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Mapping

from time import perf_counter
import time

import requests

import anyio
from fastapi import APIRouter, Body, Depends, HTTPException, status

from edge.config import (
    StationConfig,
    StorageSettings,
    load_station_config,
    load_storage_settings,
    save_station_config,
    save_storage_settings,
)

from .auth import require_token

router = APIRouter(prefix="/config", tags=["config"])

_station_lock = asyncio.Lock()
_storage_lock = asyncio.Lock()


def _serialize_station(config: StationConfig) -> Dict[str, Any]:
    payload = config.to_dict()
    if config.description:
        payload["description"] = config.description
    return payload


def _serialize_storage(settings: StorageSettings) -> Dict[str, Any]:
    return settings.to_dict()


def _serialize_influx(settings: StorageSettings) -> Dict[str, Any]:
    payload = {
        "driver": settings.driver,
        "url": settings.url,
        "org": settings.org,
        "bucket": settings.bucket,
        "token": settings.token,
        "timeout_s": settings.timeout_s,
        "verify_ssl": settings.verify_ssl,
    }
    return payload


async def _load_station() -> StationConfig:
    return await anyio.to_thread.run_sync(load_station_config)


async def _load_storage() -> StorageSettings:
    return await anyio.to_thread.run_sync(load_storage_settings)


def _shorten(text: str, limit: int = 160) -> str:
    """Normalize whitespace and truncate long payloads for display."""

    compact = " ".join(text.split())
    if len(compact) > limit:
        return f"{compact[: limit - 1]}…"
    return compact


def _check_influx_health(session: requests.Session, settings: StorageSettings) -> Dict[str, Any]:
    url = f"{settings.url.rstrip('/')}/health"
    headers: Dict[str, str] = {}
    if settings.token:
        headers["Authorization"] = f"Token {settings.token}"

    start = perf_counter()
    try:
        response = session.get(url, headers=headers, timeout=settings.timeout_s)
    except requests.RequestException as exc:  # pragma: no cover - exercised via tests
        return {
            "ok": False,
            "message": f"No se pudo conectar al endpoint /health: {exc}",
            "http_status": None,
            "latency_ms": None,
        }

    latency_ms = (perf_counter() - start) * 1000
    content_type = response.headers.get("content-type", "")

    if response.ok:
        status_text = None
        if "application/json" in content_type:
            try:
                payload = response.json()
            except ValueError:
                payload = None
            if isinstance(payload, dict):
                raw = payload.get("status") or payload.get("message")
                if isinstance(raw, str):
                    status_text = raw
        message = status_text or "El servicio de salud respondió correctamente."
        return {
            "ok": True,
            "message": message,
            "http_status": response.status_code,
            "latency_ms": round(latency_ms, 2),
        }

    body_text = response.text or ""
    message = _shorten(body_text or f"Influx devolvió {response.status_code}.")
    return {
        "ok": False,
        "message": message,
        "http_status": response.status_code,
        "latency_ms": round(latency_ms, 2),
    }


def _check_influx_write(session: requests.Session, settings: StorageSettings) -> Dict[str, Any]:
    params = [
        ("org", settings.org),
        ("bucket", settings.bucket),
        ("precision", "ns"),
        ("dryRun", "true"),
        ("dryrun", "true"),
    ]
    url = f"{settings.url.rstrip('/')}/api/v2/write"
    headers = {
        "Authorization": f"Token {settings.token}",
        "Content-Type": "text/plain; charset=utf-8",
        "User-Agent": "mcc128-edge/connection-check",
    }
    probe_line = f"edge_connection_check status=1i {time.time_ns()}"

    start = perf_counter()
    try:
        response = session.post(
            url,
            params=params,
            headers=headers,
            data=probe_line.encode("utf-8"),
            timeout=settings.timeout_s,
        )
    except requests.RequestException as exc:  # pragma: no cover - exercised via tests
        return {
            "ok": False,
            "message": f"No se pudo enviar la solicitud de prueba: {exc}",
            "http_status": None,
            "latency_ms": None,
        }

    latency_ms = (perf_counter() - start) * 1000
    body_text = response.text or ""

    if response.status_code < 300:
        return {
            "ok": True,
            "message": "Influx aceptó la escritura de validación (dry run).",
            "http_status": response.status_code,
            "latency_ms": round(latency_ms, 2),
        }

    message = _shorten(body_text or f"Influx devolvió {response.status_code}.")
    return {
        "ok": False,
        "message": message,
        "http_status": response.status_code,
        "latency_ms": round(latency_ms, 2),
    }


def _check_influx_status(settings: StorageSettings) -> Dict[str, Any]:
    session = requests.Session()
    session.verify = settings.verify_ssl
    try:
        health = _check_influx_health(session, settings)
        if health["ok"]:
            write = _check_influx_write(session, settings)
        else:
            write = {
                "ok": False,
                "message": "Se omitió la prueba de escritura porque el chequeo de salud falló.",
                "http_status": None,
                "latency_ms": None,
            }
    finally:
        session.close()

    if health["ok"] and write["ok"]:
        status = "ok"
        message = "Conexión verificada. Influx está listo para recibir datos."
    elif health["ok"]:
        status = "warning"
        message = "Influx respondió al chequeo de salud pero rechazó la prueba de escritura."
    else:
        status = "error"
        message = "No se pudo contactar al servicio de Influx."

    return {
        "status": status,
        "message": message,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "health": health,
        "write": write,
    }


@router.get("/mcc128")
async def get_station_config(_: None = Depends(require_token)) -> Dict[str, Any]:
    """Return the current MCC128 configuration."""

    config = await _load_station()
    return _serialize_station(config)


@router.put("/mcc128")
async def update_station_config(
    payload: Mapping[str, Any] = Body(..., description="Payload completo de sensors.yaml"),
    _: None = Depends(require_token),
) -> Dict[str, Any]:
    """Persist a new station configuration after validation."""

    try:
        candidate = StationConfig.from_mapping(dict(payload))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    async with _station_lock:
        await anyio.to_thread.run_sync(save_station_config, candidate)
    return _serialize_station(candidate)


@router.get("/storage")
async def get_storage_settings(_: None = Depends(require_token)) -> Dict[str, Any]:
    settings = await _load_storage()
    return _serialize_storage(settings)


@router.put("/storage")
async def update_storage_settings(
    payload: Mapping[str, Any] = Body(..., description="Payload completo de storage.yaml"),
    _: None = Depends(require_token),
) -> Dict[str, Any]:
    try:
        candidate = StorageSettings.from_mapping(dict(payload))
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    async with _storage_lock:
        await anyio.to_thread.run_sync(save_storage_settings, candidate)
    return _serialize_storage(candidate)


_ALLOWED_INFLUX_FIELDS = {
    "driver",
    "url",
    "org",
    "bucket",
    "token",
    "timeout_s",
    "verify_ssl",
}


@router.get("/influx")
async def get_influx_credentials(_: None = Depends(require_token)) -> Dict[str, Any]:
    settings = await _load_storage()
    return _serialize_influx(settings)


@router.put("/influx")
async def update_influx_credentials(
    payload: Mapping[str, Any] = Body(..., description="Campos parciales para credenciales de Influx"),
    _: None = Depends(require_token),
) -> Dict[str, Any]:
    unknown = set(payload.keys()) - _ALLOWED_INFLUX_FIELDS
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Campos no soportados: {', '.join(sorted(unknown))}",
        )

    async with _storage_lock:
        settings = await _load_storage()
        base = settings.to_dict()
        base.update({key: payload[key] for key in payload if key in _ALLOWED_INFLUX_FIELDS})
        try:
            candidate = StorageSettings.from_mapping(base)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            )
        await anyio.to_thread.run_sync(save_storage_settings, candidate)
        return _serialize_influx(candidate)


@router.get("/influx/status")
async def get_influx_status(_: None = Depends(require_token)) -> Dict[str, Any]:
    """Ejecuta una verificación de salud y escritura contra InfluxDB."""

    settings = await _load_storage()
    return await anyio.to_thread.run_sync(_check_influx_status, settings)

