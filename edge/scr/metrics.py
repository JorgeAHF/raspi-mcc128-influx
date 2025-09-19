import json
import logging
import threading
import time
from typing import Dict


class AcquisitionMetrics:
    """Thread-safe accumulator for acquisition and sender counters."""

    def __init__(self, log_interval_s: float = 30.0, logger: logging.Logger | None = None) -> None:
        self.log_interval_s = max(0.0, float(log_interval_s))
        self._logger = logger or logging.getLogger(__name__)
        self._lock = threading.Lock()
        self._start_time = time.time()
        self._last_log_time = self._start_time
        self._counters = self._initial_counters()
        self._last_snapshot = self._counters.copy()

    @staticmethod
    def _initial_counters() -> Dict[str, int]:
        return {
            "blocks_processed": 0,
            "samples_read": 0,
            "samples_enqueued": 0,
            "samples_sent": 0,
            "http_retries": 0,
            "http_retry_lines": 0,
            "queue_overruns": 0,
            "dropped_samples": 0,
            "hardware_overruns": 0,
        }

    def record_block(self, block_len: int, channel_count: int) -> None:
        total_samples = max(0, block_len) * max(0, channel_count)
        with self._lock:
            self._counters["blocks_processed"] += 1
            self._counters["samples_read"] += total_samples
            self._counters["samples_enqueued"] += total_samples
        self.maybe_log()

    def increment_samples_sent(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self._counters["samples_sent"] += count
        self.maybe_log()

    def increment_http_retry(self, retried_lines: int) -> None:
        with self._lock:
            self._counters["http_retries"] += 1
            if retried_lines > 0:
                self._counters["http_retry_lines"] += retried_lines
        self.maybe_log()

    def report_queue_overrun(self, dropped: int) -> None:
        with self._lock:
            self._counters["queue_overruns"] += 1
            if dropped > 0:
                self._counters["dropped_samples"] += dropped
        self.maybe_log()

    def increment_dropped_samples(self, count: int) -> None:
        if count <= 0:
            return
        with self._lock:
            self._counters["dropped_samples"] += count
        self.maybe_log()

    def increment_hardware_overrun(self) -> None:
        with self._lock:
            self._counters["hardware_overruns"] += 1
        self.maybe_log()

    def maybe_log(self, force: bool = False) -> None:
        now = time.time()
        with self._lock:
            interval = now - self._last_log_time
            if not force and self.log_interval_s > 0.0 and interval < self.log_interval_s:
                return

            payload = self._build_payload(now, interval)
            self._last_log_time = now
            self._last_snapshot = self._counters.copy()

        self._logger.info("acquisition_metrics %s", json.dumps(payload, sort_keys=True))

    def _build_payload(self, now: float, interval: float) -> Dict[str, object]:
        delta = {
            key: self._counters[key] - self._last_snapshot.get(key, 0)
            for key in self._counters
        }
        return {
            "type": "acquisition_metrics",
            "uptime_s": round(now - self._start_time, 3),
            "interval_s": round(interval, 3),
            "counters": self._counters.copy(),
            "delta": delta,
        }
