from __future__ import annotations

import json
import shutil
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

from edge.config import store as config_store
from edge.scr.acquisition import CalibratedBlock, CalibratedChannelBlock
from edge.webapi import app
from edge.webapi import acquisition as acquisition_module
from edge.webapi import preview as preview_module
from edge.webapi.acquisition import AcquisitionSessionManager


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch):
    monkeypatch.delenv("EDGE_WEBAPI_TOKEN", raising=False)
    monkeypatch.delenv("EDGE_WEBAPI_TOKEN_FILE", raising=False)
    monkeypatch.delenv("EDGE_LOG_ACQUISITION_PATH", raising=False)
    monkeypatch.delenv("EDGE_LOG_STORAGE_PATH", raising=False)
    monkeypatch.delenv("EDGE_LOG_SENDER_PATH", raising=False)


@pytest.fixture
def temp_config_dir(tmp_path, monkeypatch):
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    source_dir = Path("edge/config")
    for name in ("sensors.yaml", "storage.yaml"):
        shutil.copy(source_dir / name, cfg_dir / name)
    monkeypatch.setattr(config_store, "CONFIG_DIR", cfg_dir)
    return cfg_dir


@pytest.fixture
def api_client(temp_config_dir):
    return TestClient(app)


class FakeRunner:
    def __init__(self, station, storage):
        self.station = station
        self.storage = storage
        self.mode = None
        self.stop_event = threading.Event()

    def request_stop(self):
        self.stop_event.set()

    def run(self, mode="continuous", test_channel=None):
        self.mode = mode
        if test_channel is not None:
            first_channel = next(iter(self.station.channels))
            block = CalibratedBlock(
                station_id=self.station.station_id,
                timestamps_ns=[1_000_000_000, 1_000_500_000],
                channels={
                    first_channel.index: CalibratedChannelBlock(
                        index=first_channel.index,
                        name=first_channel.name,
                        unit=first_channel.unit,
                        values=[0.1, 0.2],
                    )
                },
                captured_at_ns=1_001_000_000,
            )
            test_channel.put_nowait(block)
        self.stop_event.wait(0.2)
        if test_channel is not None:
            test_channel.put_nowait(None)


@pytest.fixture
def stubbed_session_manager(monkeypatch):
    manager = AcquisitionSessionManager(
        runner_factory=lambda station, storage: FakeRunner(station, storage)
    )
    monkeypatch.setattr(acquisition_module, "session_manager", manager)
    monkeypatch.setattr(preview_module, "session_manager", manager)
    yield manager
    # restore clean manager for future tests
    fresh = AcquisitionSessionManager()
    acquisition_module.session_manager = fresh
    preview_module.session_manager = fresh


def test_get_station_config(api_client):
    response = api_client.get("/config/mcc128")
    assert response.status_code == 200
    payload = response.json()
    assert payload["station_id"]
    assert "channels" in payload


def test_update_station_config_validation(api_client):
    # Missing station_id should trigger validation error
    invalid_payload = {"acquisition": {"sample_rate_hz": 10, "block_size": 10}, "channels": []}
    response = api_client.put("/config/mcc128", json=invalid_payload)
    assert response.status_code == 422


def test_update_station_config_roundtrip(api_client, temp_config_dir):
    payload = {
        "station_id": "station-99",
        "acquisition": {
            "sample_rate_hz": 25,
            "block_size": 5,
            "duration_s": None,
            "total_samples": None,
            "drift_detection": {"correction_threshold_ns": None},
        },
        "channels": [
            {
                "index": 0,
                "name": "Test",
                "unit": "mm",
                "voltage_range": 5.0,
                "calibration": {"gain": 1, "offset": 0},
            }
        ],
    }

    response = api_client.put("/config/mcc128", json=payload)
    assert response.status_code == 200
    assert response.json()["station_id"] == "station-99"

    stored = json.loads((temp_config_dir / "sensors.yaml").read_text())
    assert stored["station_id"] == "station-99"

    roundtrip = api_client.get("/config/mcc128")
    assert roundtrip.status_code == 200
    assert roundtrip.json()["station_id"] == "station-99"


def test_update_influx_partial(api_client):
    response = api_client.put("/config/influx", json={"token": "new-token"})
    assert response.status_code == 200
    data = response.json()
    assert data["token"] == "new-token"


def test_update_influx_rejects_unknown_fields(api_client):
    response = api_client.put("/config/influx", json={"token": "value", "invalid": True})
    assert response.status_code == 400
    assert "Campos no soportados" in response.json()["detail"]


def test_storage_settings_crud(api_client, temp_config_dir):
    payload = {
        "driver": "influxdb_v2",
        "url": "http://localhost:8086",
        "org": "demo",
        "bucket": "test",
        "token": "abc",
        "retry": {"max_attempts": 2},
    }

    response = api_client.put("/config/storage", json=payload)
    assert response.status_code == 200
    stored = json.loads((temp_config_dir / "storage.yaml").read_text())
    assert stored["bucket"] == "test"

    fetched = api_client.get("/config/storage")
    assert fetched.status_code == 200
    assert fetched.json()["bucket"] == "test"


def test_acquisition_lifecycle_with_preview(api_client, stubbed_session_manager):
    start = api_client.post("/acquisition/start", json={"mode": "continuous", "preview": True})
    assert start.status_code == 202
    body = start.json()
    assert body["preview"] is True

    # Consume preview stream (SSE)
    with api_client.stream("GET", "/preview/stream") as response:
        assert response.status_code == 200
        chunks = [
            chunk.decode() if isinstance(chunk, bytes) else chunk
            for chunk in response.iter_lines()
        ]
    assert any(chunk.startswith("data: ") for chunk in chunks if chunk)

    # Allow background thread to finish
    time.sleep(0.1)
    status_resp = api_client.get("/acquisition/session")
    assert status_resp.status_code == 200
    status_payload = status_resp.json()
    assert status_payload["active"] in {False, True}

    # Attempt to stop (idempotent even if already finished)
    stop = api_client.post("/acquisition/stop")
    if stop.status_code == 200:
        summary = stop.json()["session"]
        assert summary["mode"] == "continuous"
    else:
        assert stop.status_code == 409


def test_acquisition_timed_without_preview(api_client, stubbed_session_manager):
    start = api_client.post("/acquisition/start", json={"mode": "timed", "preview": False})
    assert start.status_code == 202
    body = start.json()
    assert body["preview"] is False

    stop = api_client.post("/acquisition/stop")
    assert stop.status_code == 200


def test_logs_endpoint_filters_categories(api_client, tmp_path, monkeypatch):
    log_path = tmp_path / "acquisition.log"
    log_path.write_text(
        "\n".join(
            [
                "2024-05-10 12:00:00,000 WARNING edge.scr.acquisition: Timeout leyendo bloque",
                "2024-05-10 12:01:00,500 ERROR sender: Influx write failed",
                "2024-05-10 12:02:00,750 INFO edge.scr.acquisition: Loop heartbeat",
                "2024-05-10 12:03:00,900 CRITICAL edge.scr.acquisition: Sesión abortada",
            ]
        )
    )

    monkeypatch.setenv("EDGE_LOG_ACQUISITION_PATH", str(log_path))
    monkeypatch.setenv("EDGE_LOG_STORAGE_PATH", str(log_path))

    response = api_client.get("/logs?limit=5")
    assert response.status_code == 200
    payload = response.json()

    acquisition_messages = [entry["message"] for entry in payload["acquisition"]]
    storage_messages = [entry["message"] for entry in payload["storage"]]

    assert "Timeout leyendo bloque" in acquisition_messages
    assert "Sesión abortada" in acquisition_messages
    assert storage_messages == ["Influx write failed"]

