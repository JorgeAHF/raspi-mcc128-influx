import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest
import responses

# Allow importing scripts from the edge/scr directory.
sys.path.append(str(ROOT / "edge" / "scr"))

from sender import InfluxSender  # type: ignore  # noqa: E402


WRITE_URL = "http://example.com/api/v2/write?org=org&bucket=bucket&precision=ns"


@pytest.fixture(autouse=True)
def _influx_env(monkeypatch):
    monkeypatch.setenv("INFLUX_URL", "http://example.com")
    monkeypatch.setenv("INFLUX_ORG", "org")
    monkeypatch.setenv("INFLUX_BUCKET", "bucket")
    monkeypatch.setenv("INFLUX_TOKEN", "token")
    monkeypatch.setenv("INFLUX_BATCH_SIZE", "1")
    monkeypatch.setenv("INFLUX_RETRY_MAX_ATTEMPTS", "3")
    monkeypatch.setenv("INFLUX_RETRY_BASE_DELAY_S", "0")
    monkeypatch.setenv("INFLUX_RETRY_MAX_BACKOFF_S", "0")
    monkeypatch.setenv("INFLUX_TIMEOUT_S", "5")
    yield
    for key in list(os.environ):
        if key.startswith("INFLUX_"):
            monkeypatch.delenv(key, raising=False)


@responses.activate
def test_send_retries_and_logs_server_error(caplog):
    caplog.set_level(logging.DEBUG, logger="sender")
    responses.add(responses.POST, WRITE_URL, status=500, headers={"Retry-After": "1"}, body="server error body")
    responses.add(responses.POST, WRITE_URL, status=204)

    sender = InfluxSender(start_worker=False)
    sender._sleep = lambda _: None  # type: ignore[attr-defined]

    try:
        success = sender._send_with_retries(["m field=1 1"])  # type: ignore[arg-type]
    finally:
        sender.close()

    assert success is True
    assert len(responses.calls) == 2

    failure_logs = [record.message for record in caplog.records if "failed" in record.message]
    assert any("attempt 1/3" in msg for msg in failure_logs)
    assert any("status=500" in msg for msg in failure_logs)
    assert any("headers={'Retry-After': '1'}" in msg for msg in failure_logs)
    assert any("body=server error body" in msg for msg in failure_logs)
    assert any("succeeded after 2 attempts" in record.message for record in caplog.records)


@responses.activate
def test_send_aborts_on_unauthorized(caplog):
    caplog.set_level(logging.DEBUG, logger="sender")
    responses.add(responses.POST, WRITE_URL, status=401, body="Unauthorized")

    sender = InfluxSender(start_worker=False)
    sender._sleep = lambda _: None  # type: ignore[attr-defined]

    try:
        success = sender._send_with_retries(["m field=1 1"])  # type: ignore[arg-type]
    finally:
        sender.close()

    assert success is False
    assert len(responses.calls) == 1

    error_logs = [record.message for record in caplog.records if record.levelno >= logging.ERROR]
    assert any("HTTP 401" in msg for msg in error_logs)
    assert any("attempt 1/3" in msg for msg in error_logs)

