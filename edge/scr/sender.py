import time, queue, threading, requests, os, logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class InfluxSender:
    def __init__(self):
        self.url = os.getenv("INFLUX_URL")  # ej. http://WINDOWS_IP:8086
        self.org = os.getenv("INFLUX_ORG")
        self.bucket = os.getenv("INFLUX_BUCKET")
        self.token = os.getenv("INFLUX_TOKEN")
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

def to_line(meas, tags: dict, fields: dict, ts_ns: int):
    t = ",".join(f"{k}={v}" for k,v in tags.items())
    f = ",".join(f'{k}={v}' if isinstance(v,(int,float)) else f'{k}="{v}"' for k,v in fields.items())
    return f"{meas},{t} {f} {ts_ns}"
