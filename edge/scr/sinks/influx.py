"""Sink de almacenamiento que envía muestras a InfluxDB v2."""

from __future__ import annotations

import logging
import queue
import random
import threading
import time
from typing import Iterable, List, Mapping, MutableMapping, Optional, Sequence, TYPE_CHECKING

import requests

from .base import Sample, SampleSink

if TYPE_CHECKING:  # pragma: no cover - hints only
    from edge.config.schema import StorageSettings


logger = logging.getLogger("sender")

RETRIABLE_4XX = {408, 409, 425, 429}


class InfluxSender(SampleSink):
    """Productor asíncrono de líneas para la API de escritura de InfluxDB."""

    def __init__(
        self,
        settings: "StorageSettings",
        *,
        session: Optional[requests.Session] = None,
        start_worker: bool = True,
    ) -> None:
        if settings.driver.lower() != "influxdb_v2":
            logger.warning(
                "Storage driver '%s' no reconocido; se utilizará el flujo InfluxDB v2 por defecto.",
                settings.driver,
            )

        self.settings = settings
        self._write_url = (
            f"{settings.url.rstrip('/')}/api/v2/write?org={settings.org}&bucket={settings.bucket}&precision=ns"
        )
        self.batch_size = settings.batch_size
        self.max_attempts = settings.retry.max_attempts
        self.base_backoff = settings.retry.base_delay_s
        self.max_backoff = settings.retry.max_backoff_s
        self.timeout = settings.timeout_s
        self.token = settings.token
        self.q: "queue.Queue[str]" = queue.Queue(maxsize=settings.queue_max_size)
        self.stop = False
        self.session = session or requests.Session()
        self.session.verify = settings.verify_ssl
        self._sleep = time.sleep
        self._worker_thread: Optional[threading.Thread] = None
        if start_worker:
            self.open()

    # Implementación del protocolo SampleSink ---------------------------------
    def open(self) -> None:
        if self._worker_thread and self._worker_thread.is_alive():
            return
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()

    def handle_sample(self, sample: Sample) -> None:
        line = sample_to_line(sample)
        self.enqueue(line)

    def close(self) -> None:
        if self.stop:
            return
        self.stop = True
        if self._worker_thread:
            self._worker_thread.join()
        self.session.close()

    # API pública existente ---------------------------------------------------
    def enqueue(self, line: str) -> None:
        self._queue_lines([line], context="enqueue")

    # Lógica interna ----------------------------------------------------------
    def _worker(self) -> None:
        while not self.stop:
            lines = self._drain_batch()
            if not lines:
                continue
            success = self._send_with_retries(lines)
            if not success:
                logger.error(
                    "InfluxSender dropping %d lines after exhausting retries.",
                    len(lines),
                )

    def _drain_batch(self) -> List[str]:
        lines: List[str] = []
        try:
            line = self.q.get(timeout=1)
        except queue.Empty:
            return lines

        lines.append(line)
        while len(lines) < self.batch_size:
            try:
                lines.append(self.q.get_nowait())
            except queue.Empty:
                break
        return lines

    def _send_with_retries(self, lines: Iterable[str]) -> bool:
        data = "\n".join(lines)
        headers = {"Authorization": f"Token {self.token}"}
        url = self._write_url
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.post(url, headers=headers, data=data, timeout=self.timeout)
            except requests.RequestException as exc:
                reason = f"{type(exc).__name__}: {exc}"
                if attempt == self.max_attempts:
                    logger.error(
                        "InfluxSender write failed after %d/%d attempts (%s).", attempt, self.max_attempts, reason
                    )
                    return False
                delay = self._compute_backoff(attempt)
                logger.warning(
                    "InfluxSender write attempt %d/%d raised %s; retrying in %.2fs.",
                    attempt,
                    self.max_attempts,
                    reason,
                    delay,
                )
                self._sleep(delay)
                continue

            if response.status_code < 300:
                if attempt > 1:
                    logger.info("InfluxSender write succeeded after %d attempts.", attempt)
                return True

            reason = f"HTTP {response.status_code}"
            body = self._extract_body(response)
            headers_payload = dict(response.headers)
            should_retry = self._should_retry(response.status_code)
            log_message = (
                "InfluxSender write attempt %d/%d failed (%s). status=%s headers=%s body=%s"
            )
            payload = (
                attempt,
                self.max_attempts,
                reason,
                response.status_code,
                headers_payload,
                body,
            )

            if not should_retry or attempt == self.max_attempts:
                logger.error(log_message, *payload)
                return False

            delay = self._compute_backoff(attempt)
            logger.warning(log_message + "; retrying in %.2fs.", *payload, delay)
            self._sleep(delay)

        return False

    def _queue_lines(self, lines: Sequence[str], context: str) -> None:
        idx = 0
        try:
            for idx, ln in enumerate(lines):
                self.q.put_nowait(ln)
        except queue.Full:
            self._handle_queue_full(lines[idx:], context)

    def _handle_queue_full(self, pending_lines: Sequence[str], context: str) -> None:
        for ln in pending_lines:
            self._put_with_overflow_policy(ln, context)

    def _put_with_overflow_policy(self, line: str, context: str) -> None:
        while True:
            try:
                self.q.put_nowait(line)
                return
            except queue.Full:
                if not self._drop_oldest(context):
                    logger.error(
                        "InfluxSender unable to enqueue data during %s due to persistent congestion; dropping sample.",
                        context,
                    )
                    return

    def _drop_oldest(self, context: str) -> bool:
        try:
            self.q.get_nowait()
            self.q.task_done()
        except queue.Empty:
            logger.warning(
                "InfluxSender detected queue overflow during %s but found queue empty; dropping pending data.",
                context,
            )
            return False
        logger.warning(
            "InfluxSender queue full during %s; dropping oldest sample to relieve congestion.",
            context,
        )
        return True

    def _should_retry(self, status_code: int) -> bool:
        if status_code >= 500:
            return True
        if 400 <= status_code < 500:
            return status_code in RETRIABLE_4XX
        return False

    def _compute_backoff(self, attempt: int) -> float:
        exp_delay = self.base_backoff * (2 ** (attempt - 1))
        exp_delay = min(exp_delay, self.max_backoff) if self.max_backoff else exp_delay
        jitter = random.uniform(0, self.base_backoff) if self.base_backoff else 0.0
        total = exp_delay + jitter
        if self.max_backoff:
            total = min(total, self.max_backoff)
        return total

    @staticmethod
    def _extract_body(response: requests.Response, limit: int = 512) -> str:
        try:
            body = response.text or ""
        except Exception as exc:  # pragma: no cover - extremely raro
            return f"<unable to decode body: {exc}>"
        if len(body) <= limit:
            return body
        return f"{body[:limit]}... [truncated {len(body) - limit} chars]"


def sample_to_line(sample: Sample) -> str:
    """Convierte una muestra en el formato de línea que espera InfluxDB."""

    metadata = sample.metadata or {}
    measurement = str(metadata.get("measurement", "sample"))

    tags: MutableMapping[str, object] = {"channel": sample.channel}
    tags_payload = metadata.get("tags")
    if isinstance(tags_payload, Mapping):
        for key, value in tags_payload.items():
            tags[str(key)] = value

    extra_fields: MutableMapping[str, float] = {}
    fields_payload = metadata.get("fields")
    if isinstance(fields_payload, Mapping):
        for key, value in fields_payload.items():
            if isinstance(value, (int, float)):
                extra_fields[str(key)] = float(value)

    fields: MutableMapping[str, float] = {
        str(name): float(value)
        for name, value in sample.calibrated_values.items()
    }
    fields.update(extra_fields)

    return to_line(measurement, tags, fields, sample.timestamp_ns)


def _escape_key(value: str) -> str:
    """Escape measurement, tag and field keys for Influx line protocol."""

    return (
        str(value)
        .replace("\\", r"\\\\")
        .replace(",", r"\\,")
        .replace(" ", r"\\ ")
        .replace("=", r"\\=")
    )


def _escape_tag_value(value: object) -> str:
    """Escape tag values as specified by the Influx line protocol."""

    return _escape_key(value)


def _format_field_value(value: object) -> str:
    """Format a field value according to the Influx line protocol."""

    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value}i"
    if isinstance(value, float):
        return format(value, ".15g")

    escaped = (
        str(value)
        .replace("\\", r"\\\\")
        .replace("\"", r"\\\"")
        .replace("\n", r"\\n")
    )
    return f'"{escaped}"'


def to_line(meas: str, tags: Mapping[str, object], fields: Mapping[str, object], ts_ns: int) -> str:
    measurement = _escape_key(meas)
    tags_payload = ",".join(
        f"{_escape_key(k)}={_escape_tag_value(v)}" for k, v in sorted(tags.items())
    )
    fields_payload = ",".join(
        f"{_escape_key(k)}={_format_field_value(v)}" for k, v in fields.items()
    )

    if tags_payload:
        prefix = f"{measurement},{tags_payload}"
    else:
        prefix = measurement

    return f"{prefix} {fields_payload} {ts_ns}"
