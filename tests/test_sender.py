import logging
import sys
from pathlib import Path

import pytest
import responses

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Allow importing scripts from the edge/scr directory.
SCR_PATH = ROOT / "edge" / "scr"
if str(SCR_PATH) not in sys.path:
    sys.path.append(str(SCR_PATH))

from edge.config.schema import RetrySettings, StorageSettings  # type: ignore  # noqa: E402
from sender import InfluxSender  # type: ignore  # noqa: E402


WRITE_URL = "http://example.com/api/v2/write?org=org&bucket=bucket&precision=ns"


def _make_settings(**overrides) -> StorageSettings:
    retry = overrides.pop(
        "retry",
        RetrySettings(max_attempts=3, base_delay_s=0.0, max_backoff_s=0.0),
    )
    data = {
        "driver": "influxdb_v2",
        "url": "http://example.com",
        "org": "org",
        "bucket": "bucket",
        "token": "token",
        "batch_size": 1,
        "timeout_s": 5.0,
        "queue_max_size": overrides.pop("queue_max_size", 1000),
        "verify_ssl": overrides.pop("verify_ssl", True),
        "retry": retry,
    }
    data.update(overrides)
    return StorageSettings(**data)


@responses.activate
def test_send_retries_and_logs_server_error(caplog):
    caplog.set_level(logging.DEBUG, logger="sender")
    responses.add(responses.POST, WRITE_URL, status=500, headers={"Retry-After": "1"}, body="server error body")
    responses.add(responses.POST, WRITE_URL, status=204)

    sender = InfluxSender(_make_settings(), start_worker=False)
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

    sender = InfluxSender(_make_settings(), start_worker=False)
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

