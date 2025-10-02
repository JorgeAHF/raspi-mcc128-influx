"""System status endpoints (time synchronization, etc.)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Iterable

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from .auth import require_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/system",
    tags=["system"],
    dependencies=[Depends(require_token)],
)


class TimeStatus(BaseModel):
    """Expose information about the current system time and NTP status."""

    system_time: datetime
    timezone: str | None = None
    ntp_enabled: bool | None = None
    ntp_synchronized: bool | None = None
    last_successful_sync: datetime | None = None
    last_attempt_sync: datetime | None = None
    server_name: str | None = None
    server_address: str | None = None


class SyncTimeResponse(BaseModel):
    """Response payload for the NTP sync action."""

    message: str
    warnings: list[str]
    time: TimeStatus


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_usec(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        microseconds = int(value)
    except ValueError:
        return None
    if microseconds <= 0:
        return None
    # systemd exposes timestamps in microseconds since the UNIX epoch (UTC)
    timestamp = datetime.fromtimestamp(microseconds / 1_000_000, tz=timezone.utc)
    return timestamp.astimezone()


def _parse_key_value(output: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            data[key] = value
    return data


def _run_command(args: Iterable[str]) -> str:
    args_list = list(args)
    try:
        completed = subprocess.run(
            args_list,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"Comando no encontrado: {args_list!r}") from exc
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if exc.stderr else exc.stdout.strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(
            f"El comando {' '.join(args_list)} finalizó con código {exc.returncode}{detail}"
        ) from exc
    return completed.stdout


def _gather_time_status() -> TimeStatus:
    system_time = datetime.now().astimezone()
    timezone_name: str | None = None
    ntp_enabled: bool | None = None
    ntp_synchronized: bool | None = None
    last_successful_sync: datetime | None = None
    last_attempt_sync: datetime | None = None
    server_name: str | None = None
    server_address: str | None = None

    try:
        show_output = _run_command(
            [
                "timedatectl",
                "show",
                "--property=Timezone",
                "--property=NTPSyncEnabled",
                "--property=NTPSynchronized",
                "--property=TimeUSec",
            ]
        )
    except RuntimeError as exc:
        logger.debug("No se pudo obtener el estado horario principal: %s", exc)
    else:
        info = _parse_key_value(show_output)
        timezone_name = info.get("Timezone") or None
        ntp_enabled = _parse_bool(info.get("NTPSyncEnabled"))
        ntp_synchronized = _parse_bool(info.get("NTPSynchronized"))
        parsed_time = _parse_usec(info.get("TimeUSec"))
        if parsed_time is not None:
            system_time = parsed_time

    try:
        timesync_output = _run_command(
            [
                "timedatectl",
                "show-timesync",
                "--property=ServerName",
                "--property=ServerAddress",
                "--property=LastSuccessfulSyncUSec",
                "--property=LastAttemptSyncUSec",
                "--property=LastSyncUSec",
            ]
        )
    except RuntimeError as exc:
        logger.debug("No se pudo obtener el estado de timesyncd: %s", exc)
    else:
        info = _parse_key_value(timesync_output)
        server_name = info.get("ServerName") or None
        server_address = info.get("ServerAddress") or None
        last_successful_sync = _parse_usec(info.get("LastSuccessfulSyncUSec"))
        last_attempt_sync = _parse_usec(info.get("LastAttemptSyncUSec"))
        if last_successful_sync is None:
            last_successful_sync = _parse_usec(info.get("LastSyncUSec"))

    return TimeStatus(
        system_time=system_time,
        timezone=timezone_name,
        ntp_enabled=ntp_enabled,
        ntp_synchronized=ntp_synchronized,
        last_successful_sync=last_successful_sync,
        last_attempt_sync=last_attempt_sync,
        server_name=server_name,
        server_address=server_address,
    )


@router.get("/time", response_model=TimeStatus)
async def get_time_status() -> TimeStatus:
    """Return the current system time information."""

    return _gather_time_status()


@router.post("/time/sync", response_model=SyncTimeResponse, status_code=status.HTTP_200_OK)
async def sync_time() -> SyncTimeResponse:
    """Trigger a synchronization attempt with the configured NTP source."""

    warnings: list[str] = []

    try:
        _run_command(["timedatectl", "set-ntp", "true"])
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc))

    systemctl_path = shutil.which("systemctl")
    if systemctl_path:
        try:
            _run_command([systemctl_path, "restart", "systemd-timesyncd.service"])
        except RuntimeError as exc:
            warnings.append(str(exc))
    else:
        warnings.append("systemctl no está disponible; no se reinició systemd-timesyncd.")

    try:
        # Touch the timesync status so that timesyncd performs an update soon.
        _run_command(["timedatectl", "timesync-status"])
    except RuntimeError as exc:
        warnings.append(str(exc))

    return SyncTimeResponse(
        message="Sincronización NTP solicitada.",
        warnings=warnings,
        time=_gather_time_status(),
    )


__all__ = ["router"]
