import logging
import os
import queue
import random
import threading
import time
from pathlib import Path
from typing import Iterable, List, Optional

import requests


logger = logging.getLogger(__name__)


def _running_under_systemd() -> bool:
    return any(os.getenv(var) for var in ("INVOCATION_ID", "SYSTEMD_EXEC_PID", "JOURNAL_STREAM"))


def _load_dotenv_if_needed():
    if _running_under_systemd():
        return
    try:
        from dotenv import load_dotenv  # type: ignore
    except ImportError:
        logger.warning("python-dotenv no está disponible; continúo sin cargar .env")
        return

    env_path = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(env_path, override=False)


_load_dotenv_if_needed()

RETRIABLE_4XX = {408, 409, 425, 429}


class InfluxSender:
    def __init__(self, *, session: Optional[requests.Session] = None, start_worker: bool = True):
        self.url = os.getenv("INFLUX_URL")  # ej. http://WINDOWS_IP:8086
        self.org = os.getenv("INFLUX_ORG")
        self.bucket = os.getenv("INFLUX_BUCKET")
        self.token = os.getenv("INFLUX_TOKEN")
        self.batch_size = self._read_int_env("INFLUX_BATCH_SIZE", default=5, minimum=1)
        self.max_attempts = self._read_int_env("INFLUX_RETRY_MAX_ATTEMPTS", default=5, minimum=1)
        self.base_backoff = self._read_float_env("INFLUX_RETRY_BASE_DELAY_S", default=1.0, minimum=0.0)
        self.max_backoff = self._read_float_env("INFLUX_RETRY_MAX_BACKOFF_S", default=30.0, minimum=0.0)
        self.timeout = self._read_float_env("INFLUX_TIMEOUT_S", default=5.0, minimum=0.1)
        missing = [
            name
            for name, value in (
                ("INFLUX_URL", self.url),
                ("INFLUX_ORG", self.org),
                ("INFLUX_BUCKET", self.bucket),
                ("INFLUX_TOKEN", self.token),
            )
            if not value
        ]
        if missing:
            if _running_under_systemd():
                hint = (
                    "Defina las variables faltantes en el archivo de servicio systemd, por ejemplo con "
                    "Environment=INFLUX_URL=..."
                )
            else:
                hint = "Defina las variables faltantes en edge/.env o expórtelas en su shell antes de ejecutar."
            raise RuntimeError(
                "Faltan configuraciones obligatorias: %s. %s" % (", ".join(missing), hint)
            )
        self.q = queue.Queue(maxsize=1000)
        self.stop = False
        self.session = session or requests.Session()
        self._sleep = time.sleep
        self._worker_thread: Optional[threading.Thread] = None
        if start_worker:
            self._worker_thread = threading.Thread(target=self._worker, daemon=True)
            self._worker_thread.start()

    @staticmethod
    def _read_int_env(name: str, default: int, minimum: int) -> int:
        try:
            value = int(os.getenv(name, default))
        except ValueError:
            logger.warning("Valor inválido para %s; usando %s", name, default)
            value = default
        return max(value, minimum)

    @staticmethod
    def _read_float_env(name: str, default: float, minimum: float) -> float:
        try:
            value = float(os.getenv(name, default))
        except ValueError:
            logger.warning("Valor inválido para %s; usando %s", name, default)
            value = default
        return max(value, minimum)

    def _worker(self):
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
        url = f"{self.url}/api/v2/write?org={self.org}&bucket={self.bucket}&precision=ns"
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
        except Exception as exc:  # pragma: no cover - extremely rare
            return f"<unable to decode body: {exc}>"
        if len(body) <= limit:
            return body
        return f"{body[:limit]}... [truncated {len(body) - limit} chars]"

    def enqueue(self, line: str):
        self._queue_lines([line], context="enqueue")

    def close(self):
        if self.stop:
            return
        self.stop = True
        if self._worker_thread:
            self._worker_thread.join()
        self.session.close()

    def _queue_lines(self, lines, context: str):
        idx = 0
        try:
            for idx, ln in enumerate(lines):
                self.q.put_nowait(ln)
        except queue.Full:
            self._handle_queue_full(lines[idx:], context)

    def _handle_queue_full(self, pending_lines, context: str):
        for ln in pending_lines:
            self._put_with_overflow_policy(ln, context)

    def _put_with_overflow_policy(self, line, context: str):
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

def _escape_key(value: str) -> str:
    """Escape measurement, tag and field keys for Influx line protocol."""

    return (
        str(value)
        .replace("\\", r"\\\\")
        .replace(",", r"\\,")
        .replace(" ", r"\\ ")
        .replace("=", r"\\=")
    )


def _escape_tag_value(value) -> str:
    """Escape tag values as specified by the Influx line protocol."""

    return _escape_key(value)


def _format_field_value(value) -> str:
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


def to_line(meas, tags: dict, fields: dict, ts_ns: int):
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
