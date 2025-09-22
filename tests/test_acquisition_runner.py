"""Unit tests covering AcquisitionRunner control flow."""

from __future__ import annotations

from types import SimpleNamespace
from typing import List

import pytest

from edge.config.schema import StationConfig, StorageSettings
from edge.scr import acquisition as acquisition_module
from edge.scr.acquisition import AcquisitionRunner
from edge.scr.sinks import Sample


@pytest.fixture()
def station_config() -> StationConfig:
    return StationConfig.from_mapping(
        {
            "station_id": "station-01",
            "acquisition": {
                "sample_rate_hz": 100.0,
                "block_size": 4,
                "duration_s": None,
                "total_samples": None,
                "drift_detection": {"correction_threshold_ns": None},
            },
            "channels": [
                {
                    "index": 0,
                    "name": "Canal 0",
                    "unit": "mm",
                    "voltage_range": 5.0,
                    "calibration": {"gain": 1.0, "offset": 0.0},
                }
            ],
        }
    )


@pytest.fixture()
def storage_settings() -> StorageSettings:
    return StorageSettings.from_mapping(
        {
            "driver": "influxdb_v2",
            "url": "http://localhost:8086",
            "org": "demo",
            "bucket": "bucket",
            "token": "token",
            "retry": {"max_attempts": 2},
        }
    )


class RecordingSink:
    def __init__(self) -> None:
        self.open_called = False
        self.closed = False
        self.samples: List[Sample] = []

    def open(self) -> None:
        self.open_called = True

    def handle_sample(self, sample: Sample) -> None:
        self.samples.append(sample)

    def close(self) -> None:
        self.closed = True


def build_fake_board():
    return SimpleNamespace(
        a_in_scan_stop=lambda: None,
        a_in_scan_cleanup=lambda: None,
    )


def test_run_continuous_dispatches_samples(monkeypatch, station_config, storage_settings):
    sink = RecordingSink()
    runner = AcquisitionRunner(
        station=station_config,
        storage=storage_settings,
        sink_factory=lambda _: [sink],
    )

    monkeypatch.setattr(acquisition_module, "open_mcc128", lambda: build_fake_board())
    monkeypatch.setattr(
        acquisition_module,
        "start_scan",
        lambda board, channel_indices, sample_rate_hz, **kwargs: (0x1, 4),
    )

    def fake_read_block(board, mask, block_samples, channel_indices, **kwargs):
        runner.request_stop()
        return {channel_indices[0]: [0.1, 0.2, 0.3, 0.4]}

    monkeypatch.setattr(acquisition_module, "read_block", fake_read_block)

    runner.run(mode="continuous")

    assert sink.open_called is True
    assert sink.closed is True
    assert [sample.calibrated_values["valor"] for sample in sink.samples] == [0.1, 0.2, 0.3, 0.4]


def test_run_timed_stops_after_total_samples(monkeypatch, storage_settings):
    station = StationConfig.from_mapping(
        {
            "station_id": "station-02",
            "acquisition": {
                "sample_rate_hz": 50.0,
                "block_size": 6,
                "duration_s": 5.0,
                "total_samples": 3,
                "drift_detection": {"correction_threshold_ns": None},
            },
            "channels": [
                {
                    "index": 0,
                    "name": "Canal 0",
                    "unit": "mm",
                    "voltage_range": 5.0,
                    "calibration": {"gain": 1.0, "offset": 0.0},
                }
            ],
        }
    )

    sink = RecordingSink()
    runner = AcquisitionRunner(
        station=station,
        storage=storage_settings,
        sink_factory=lambda _: [sink],
    )

    monkeypatch.setattr(acquisition_module, "open_mcc128", lambda: build_fake_board())
    monkeypatch.setattr(
        acquisition_module,
        "start_scan",
        lambda board, channel_indices, sample_rate_hz, **kwargs: (0x1, 6),
    )

    def fake_read_block(board, mask, block_samples, channel_indices, **kwargs):
        return {channel_indices[0]: [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}

    monkeypatch.setattr(acquisition_module, "read_block", fake_read_block)

    runner.run(mode="timed")

    assert sink.open_called is True
    assert sink.closed is True
    assert [sample.calibrated_values["valor"] for sample in sink.samples] == [1.0, 2.0, 3.0]
