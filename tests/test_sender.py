import sys
import threading
from pathlib import Path
from typing import List

import pytest

# Allow importing scripts from the edge/scr directory.
sys.path.append(str(Path(__file__).resolve().parents[1] / "edge" / "scr"))

import sender  # type: ignore  # noqa: E402


class _Response:
    status_code = 204


@pytest.fixture(autouse=True)
def _influx_env(monkeypatch):
    monkeypatch.setenv("INFLUX_URL", "http://example.com")
    monkeypatch.setenv("INFLUX_ORG", "test-org")
    monkeypatch.setenv("INFLUX_BUCKET", "test-bucket")
    monkeypatch.setenv("INFLUX_TOKEN", "test-token")


def test_close_waits_for_pending_data(monkeypatch):
    received_lines: List[str] = []
    post_calls = threading.Event()

    def fake_post(url, headers, data, timeout):
        received_lines.extend(data.split("\n"))
        if len(received_lines) >= 7:
            post_calls.set()
        return _Response()

    monkeypatch.setattr(sender.requests, "post", fake_post)

    influx = sender.InfluxSender()
    lines = [f"measurement value={idx} {idx}" for idx in range(7)]
    try:
        for line in lines:
            influx.enqueue(line)

        influx.close()

        assert post_calls.is_set(), "close() should wait until all queued data is sent"
        assert received_lines == lines
    finally:
        influx.close()
