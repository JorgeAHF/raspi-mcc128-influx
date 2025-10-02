"""Endpoints to expose recent log entries for troubleshooting."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from .auth import require_token

LogCategory = Literal["acquisition", "storage"]

router = APIRouter(prefix="/logs", tags=["logs"])


LOG_LINE_PATTERN = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3})\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<logger>[^:]+):\s+"
    r"(?P<message>.*)$"
)


@dataclass
class ParsedLogLine:
    timestamp: datetime
    level: str
    logger: str
    message: str
    category: LogCategory


class LogEntry(BaseModel):
    timestamp: datetime = Field(description="Marca temporal del evento de log")
    level: str = Field(description="Nivel de severidad (WARNING/ERROR/CRITICAL)")
    logger: str = Field(description="Nombre del logger que emitió el mensaje")
    message: str = Field(description="Contenido del mensaje de log")
    category: LogCategory = Field(description="Categoría inferida del evento")


class LogsResponse(BaseModel):
    acquisition: list[LogEntry] = Field(
        default_factory=list,
        description="Eventos relevantes de la adquisición MCC128",
    )
    storage: list[LogEntry] = Field(
        default_factory=list,
        description="Eventos relevantes del almacenamiento InfluxDB",
    )


def _resolve_log_paths() -> dict[LogCategory, Path]:
    """Return log file paths based on environment variables."""

    acquisition_path = Path(
        os.environ.get("EDGE_LOG_ACQUISITION_PATH", "/var/log/edge/acquisition.log")
    )
    storage_path = Path(
        os.environ.get(
            "EDGE_LOG_STORAGE_PATH",
            os.environ.get("EDGE_LOG_SENDER_PATH", str(acquisition_path)),
        )
    )
    return {"acquisition": acquisition_path, "storage": storage_path}


def _tail_lines(path: Path, max_lines: int) -> list[str]:
    """Return the last ``max_lines`` lines from ``path`` safely."""

    if not path.exists() or not path.is_file():
        return []

    chunk_size = 4096
    buffer = bytearray()
    newline_count = 0
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            while position > 0 and newline_count <= max_lines:
                read_size = min(chunk_size, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size)
                buffer = chunk + buffer
                newline_count = buffer.count(b"\n")
                if position == 0:
                    break
    except OSError as exc:  # pragma: no cover - unexpected I/O failure
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"No se pudo leer el log {path}: {exc}",
        ) from exc

    text = buffer.decode("utf-8", errors="replace")
    lines = text.splitlines()
    return lines[-max_lines:]


def _categorize(logger_name: str, message: str) -> LogCategory:
    lowered_logger = logger_name.lower()
    lowered_message = message.lower()
    if any(keyword in lowered_logger for keyword in ("sender", "influx", "sink")):
        return "storage"
    if "influx" in lowered_message:
        return "storage"
    return "acquisition"


def _parse_line(line: str) -> ParsedLogLine | None:
    match = LOG_LINE_PATTERN.match(line.strip())
    if not match:
        return None
    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S,%f")
    except ValueError:
        return None
    level = match.group("level")
    if level not in {"WARNING", "ERROR", "CRITICAL"}:
        return None
    logger_name = match.group("logger")
    message = match.group("message")
    category = _categorize(logger_name, message)
    return ParsedLogLine(timestamp, level, logger_name, message, category)


def _collect_recent_logs(limit: int) -> LogsResponse:
    paths = _resolve_log_paths()
    # Avoid reading the same file twice if both categories share it.
    unique_paths = {path for path in paths.values()}
    parsed: list[ParsedLogLine] = []
    for path in unique_paths:
        for line in _tail_lines(path, max_lines=limit * 6):
            parsed_line = _parse_line(line)
            if parsed_line:
                parsed.append(parsed_line)
    parsed.sort(key=lambda item: item.timestamp)

    acquisition_entries = [
        LogEntry(**parsed_line.__dict__)
        for parsed_line in parsed
        if parsed_line.category == "acquisition"
    ][-limit:]

    storage_entries = [
        LogEntry(**parsed_line.__dict__)
        for parsed_line in parsed
        if parsed_line.category == "storage"
    ][-limit:]

    return LogsResponse(acquisition=acquisition_entries, storage=storage_entries)


@router.get("", response_model=LogsResponse, dependencies=[Depends(require_token)])
def get_recent_logs(limit: int = Query(50, ge=1, le=500)) -> LogsResponse:
    """Return the most recent warning/error log entries for troubleshooting."""

    return _collect_recent_logs(limit)
