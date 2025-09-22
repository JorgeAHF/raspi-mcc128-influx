"""Configuration endpoints exposing typed schemas."""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Mapping

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

