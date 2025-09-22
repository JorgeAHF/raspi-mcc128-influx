"""Sink que persiste muestras en archivos CSV rotativos."""

from __future__ import annotations

import csv
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Sequence, TextIO

from edge.config.schema import CSVSinkSettings

from .base import Sample, SampleSink

logger = logging.getLogger(__name__)


class CSVSink(SampleSink):
    """Escribe muestras en archivos CSV con rotación por sesión o fecha."""

    def __init__(self, settings: CSVSinkSettings) -> None:
        self.settings = replace(settings, enabled=True)
        self._session_id: str = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self._files: Dict[str, TextIO] = {}
        self._writers: Dict[str, csv.writer] = {}
        self._headers: Dict[str, List[str]] = {}
        self._paths: Dict[str, Path] = {}

    # API del SampleSink ------------------------------------------------------
    def open(self) -> None:
        Path(self.settings.directory).mkdir(parents=True, exist_ok=True)

    def handle_sample(self, sample: Sample) -> None:
        key = self._rotation_key(sample)
        writer = self._ensure_writer(key, sample)
        headers, row_map = self._prepare_row(sample)
        stored_headers = self._headers.get(key)
        if stored_headers is None:
            stored_headers = headers
            self._headers[key] = headers
            if self.settings.write_headers:
                writer.writerow(stored_headers)
        values = [self._format_value(row_map.get(column)) for column in stored_headers]
        writer.writerow(values)
        file_obj = self._files.get(key)
        if file_obj:
            file_obj.flush()

    def close(self) -> None:
        for fh in list(self._files.values()):
            try:
                fh.flush()
            except Exception:  # pragma: no cover - best effort
                pass
            try:
                fh.close()
            except Exception:  # pragma: no cover - best effort
                logger.exception("Error al cerrar archivo CSV")
        self._files.clear()
        self._writers.clear()

    # API auxiliar ------------------------------------------------------------
    def flush(self) -> None:
        for fh in self._files.values():
            try:
                fh.flush()
            except Exception:  # pragma: no cover - best effort
                logger.exception("No se pudo hacer flush de archivo CSV")

    def list_files(self) -> Sequence[Path]:
        return list(self._paths.values())

    # Métodos internos --------------------------------------------------------
    def _rotation_key(self, sample: Sample) -> str:
        if self.settings.rotation == "daily":
            dt = datetime.fromtimestamp(sample.timestamp_ns / 1e9, tz=timezone.utc)
            return dt.strftime("%Y%m%d")
        return self._session_id

    def _ensure_writer(self, key: str, sample: Sample) -> csv.writer:
        writer = self._writers.get(key)
        if writer is not None:
            return writer
        filename = self._filename_for_key(key, sample)
        path = Path(self.settings.directory) / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("a", encoding=self.settings.encoding, newline=self.settings.newline)
        writer = csv.writer(fh, delimiter=self.settings.delimiter)
        self._files[key] = fh
        self._writers[key] = writer
        self._paths[key] = path
        return writer

    def _filename_for_key(self, key: str, sample: Sample) -> str:
        station = self._extract_station(sample.metadata)
        parts = [self.settings.filename_prefix]
        if station:
            parts.append(station)
        parts.append(key)
        return "_".join(parts) + ".csv"

    @staticmethod
    def _extract_station(metadata: Mapping[str, object]) -> Optional[str]:
        station = metadata.get("station_id") or metadata.get("station")
        if not station:
            return None
        return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in str(station))

    def _prepare_row(self, sample: Sample) -> tuple[List[str], Dict[str, object]]:
        dt = datetime.fromtimestamp(sample.timestamp_ns / 1e9, tz=timezone.utc)
        timestamp_text = dt.strftime(self.settings.timestamp_format)
        headers: List[str] = ["timestamp", "timestamp_ns", "channel"]
        row: Dict[str, object] = {
            "timestamp": timestamp_text,
            "timestamp_ns": sample.timestamp_ns,
            "channel": sample.channel,
        }

        for name in sorted(sample.calibrated_values.keys()):
            header = f"value_{name}"
            headers.append(header)
            row[header] = sample.calibrated_values[name]

        metadata = sample.metadata or {}
        measurement = metadata.get("measurement")
        if measurement is not None:
            headers.append("measurement")
            row["measurement"] = measurement

        tags = metadata.get("tags")
        if isinstance(tags, Mapping):
            for name in sorted(tags.keys()):
                header = f"tag_{name}"
                headers.append(header)
                row[header] = tags[name]

        for name in sorted(metadata.keys()):
            if name in {"measurement", "tags", "fields"}:
                continue
            header = f"meta_{name}"
            if header not in headers:
                headers.append(header)
            row[header] = metadata[name]

        extra_fields = metadata.get("fields")
        if isinstance(extra_fields, Mapping):
            for name in sorted(extra_fields.keys()):
                header = f"extra_{name}"
                if header not in headers:
                    headers.append(header)
                row[header] = extra_fields[name]

        return headers, row

    def _format_value(self, value: object) -> object:
        if isinstance(value, float):
            text = format(value, ".15g")
            if self.settings.decimal != ".":
                text = text.replace(".", self.settings.decimal)
            return text
        if isinstance(value, (int, str)):
            return value
        if value is None:
            return ""
        return str(value)
