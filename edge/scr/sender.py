import time, queue, threading, requests, os
from datetime import datetime, timezone

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
                    # re-enqueue si falla (simple)
                    for ln in lines: self.q.put_nowait(ln)
                    time.sleep(2)
            except Exception:
                for ln in lines: self.q.put_nowait(ln)
                time.sleep(2)

    def enqueue(self, line: str):
        try:
            self.q.put_nowait(line)
        except queue.Full:
            # último recurso: drop con marca
            pass

def to_line(meas, tags: dict, fields: dict, ts_ns: int):
    t = ",".join(f"{k}={v}" for k,v in tags.items())
    f = ",".join(f'{k}={v}' if isinstance(v,(int,float)) else f'{k}="{v}"' for k,v in fields.items())
    return f"{meas},{t} {f} {ts_ns}"
