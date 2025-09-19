import time, queue, threading, requests, os, logging
from datetime import datetime, timezone
from pathlib import Path


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

class InfluxSender:
    def __init__(self):
        self.url = os.getenv("INFLUX_URL")  # ej. http://WINDOWS_IP:8086
        self.org = os.getenv("INFLUX_ORG")
        self.bucket = os.getenv("INFLUX_BUCKET")
        self.token = os.getenv("INFLUX_TOKEN")
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
        self.t = threading.Thread(target=self._worker, daemon=True)
        self.t.start()

    def _worker(self):
        while not self.stop:
            lines = []
            try:
                # junta hasta 5 bloques para eficiencia
                for _ in range(5):
                    lines.append(self.q.get(timeout=1))
            except queue.Empty:
                pass
            if not lines: continue
            data = "\n".join(lines)
            headers = {"Authorization": f"Token {self.token}"}
            try:
                r = requests.post(
                    f"{self.url}/api/v2/write?org={self.org}&bucket={self.bucket}&precision=ns",
                    headers=headers, data=data, timeout=5
                )
                if r.status_code >= 300:
                    logger.warning(
                        "InfluxSender write failed with status %s; re-queueing %d lines.",
                        r.status_code,
                        len(lines),
                    )
                    # re-enqueue si falla (simple)
                    self._queue_lines(lines, context=f"HTTP {r.status_code} retry")
                    time.sleep(2)
            except Exception as exc:
                logger.warning(
                    "InfluxSender write raised %s; re-queueing %d lines.",
                    exc,
                    len(lines),
                )
                self._queue_lines(lines, context=f"exception {type(exc).__name__}")
                time.sleep(2)

    def enqueue(self, line: str):
        self._queue_lines([line], context="enqueue")

    def close(self):
        if self.stop:
            return
        self.stop = True
        self.t.join()

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
