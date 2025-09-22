"""Unit tests for the different sink implementations."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List

import pytest
import requests

from edge.config.schema import CSVSinkSettings, FTPSinkSettings, StorageSettings
from edge.scr.sinks import CSVSink, FTPSink, InfluxSender, Sample
from edge.scr.sinks.influx import sample_to_line


def make_sample(timestamp_ns: int = 1_000_000_000) -> Sample:
    return Sample(
        channel=0,
        timestamp_ns=timestamp_ns,
        calibrated_values={"valor": 1.234},
        metadata={
            "measurement": "lvdt",
            "tags": {"sensor": "LVDT", "pi": "station-01"},
            "station_id": "station-01",
            "sensor_name": "LVDT",
            "unit": "mm",
        },
    )


def test_csv_sink_writes_headers_and_values(tmp_path):
    settings = CSVSinkSettings.from_mapping({"enabled": True, "directory": str(tmp_path)})
    sink = CSVSink(settings)
    sink.open()
    sink.handle_sample(make_sample())
    sink.close()

    files = sink.list_files()
    assert len(files) == 1
    csv_path = Path(files[0])
    assert csv_path.exists()

    with csv_path.open(newline="") as fh:
        rows = list(csv.reader(fh))

    headers = rows[0]
    values = rows[1]
    row_map = dict(zip(headers, values))

    assert row_map["value_valor"] == "1.234"
    assert row_map["tag_sensor"] == "LVDT"
    assert row_map["meta_station_id"] == "station-01"


class DummyFTP:
    def __init__(self) -> None:
        self.connected = False
        self.login_args = None
        self.passive = None
        self.cwd_calls: List[str] = []
        self.created_dirs: List[str] = []
        self.uploads: List[tuple[str, bytes]] = []

    def connect(self, host, port):
        self.connected = (host, port)

    def login(self, username, password):
        self.login_args = (username, password)

    def set_pasv(self, passive):
        self.passive = passive

    def cwd(self, path):
        self.cwd_calls.append(path)

    def mkd(self, path):
        self.created_dirs.append(path)

    def storbinary(self, command, fh):
        self.uploads.append((command, fh.read()))

    def close(self):
        pass


def test_ftp_sink_uploads_generated_csv(monkeypatch, tmp_path):
    csv_settings = CSVSinkSettings.from_mapping({"enabled": True, "directory": str(tmp_path)})
    ftp_settings = FTPSinkSettings.from_mapping(
        {
            "enabled": True,
            "protocol": "ftp",
            "host": "example.org",
            "username": "user",
            "password": "secret",
            "remote_dir": "/incoming",
            "local_dir": str(tmp_path / "out"),
        }
    )

    dummy_ftp = DummyFTP()
    monkeypatch.setattr("edge.scr.sinks.ftp.ftplib.FTP", lambda: dummy_ftp)

    sink = FTPSink(ftp_settings, csv_settings)
    sink.open()
    sink.handle_sample(make_sample())
    sink.close()

    assert dummy_ftp.connected == ("example.org", 21)
    assert dummy_ftp.login_args == ("user", "secret")
    assert any(cmd.startswith("STOR ") for cmd, _ in dummy_ftp.uploads)


class FakeResponse:
    def __init__(self, status_code: int, text: str = "", headers: dict | None = None) -> None:
        self.status_code = status_code
        self._text = text
        self.headers = headers or {}

    @property
    def text(self) -> str:  # pragma: no cover - property invoked indirectly
        return self._text


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.verify = True
        self.calls: List[dict] = []
        self.closed = False

    def post(self, url, headers=None, data=None, timeout=None):
        action = self._responses.pop(0)
        if isinstance(action, Exception):
            raise action
        self.calls.append({"url": url, "headers": headers, "data": data, "timeout": timeout})
        return action

    def close(self):
        self.closed = True


def build_storage_settings() -> StorageSettings:
    return StorageSettings.from_mapping(
        {
            "driver": "influxdb_v2",
            "url": "http://localhost:8086",
            "org": "demo",
            "bucket": "bucket",
            "token": "token",
            "retry": {"max_attempts": 3, "base_delay_s": 0, "max_backoff_s": 0},
        }
    )


def test_influx_sender_retries_and_succeeds(monkeypatch):
    storage = build_storage_settings()
    responses = [
        requests.RequestException("boom"),
        FakeResponse(500, "fail"),
        FakeResponse(204, ""),
    ]
    session = FakeSession(responses)
    sender = InfluxSender(storage, session=session, start_worker=False)
    sender._sleep = lambda delay: None

    line = sample_to_line(make_sample())
    success = sender._send_with_retries([line])

    assert success is True
    assert len(session.calls) == 2
    assert session.closed is False

