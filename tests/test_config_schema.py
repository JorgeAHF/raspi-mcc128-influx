"""Unit tests for the typed configuration schema helpers."""

from __future__ import annotations

import pytest

from edge.config.schema import (
    AcquisitionSettings,
    CSVSinkSettings,
    FTPSinkSettings,
    StationConfig,
    StorageSettings,
)


def build_station_payload(**overrides):
    payload = {
        "station_id": "station-01",
        "description": "Banco de pruebas",
        "acquisition": {
            "sample_rate_hz": 10.0,
            "block_size": 20,
            "duration_s": None,
            "total_samples": None,
            "drift_detection": {"correction_threshold_ns": 2_000_000},
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
    payload.update(overrides)
    return payload


def test_station_config_requires_unique_channel_indices():
    payload = build_station_payload(
        channels=[
            {
                "index": 0,
                "name": "A",
                "unit": "mm",
                "voltage_range": 5.0,
            },
            {
                "index": 0,
                "name": "Duplicado",
                "unit": "mm",
                "voltage_range": 5.0,
            },
        ]
    )

    with pytest.raises(ValueError, match="canal duplicado"):
        StationConfig.from_mapping(payload)


def test_acquisition_settings_validate_positive_sample_rate():
    payload = build_station_payload()
    payload["acquisition"]["sample_rate_hz"] = -1

    with pytest.raises(ValueError, match="sample_rate_hz debe ser > 0"):
        AcquisitionSettings.from_mapping(payload["acquisition"])


def test_storage_settings_parse_sinks_from_string_list():
    payload = {
        "driver": "influxdb_v2",
        "url": "http://localhost:8086",
        "org": "demo",
        "bucket": "bucket",
        "token": "token",
        "sinks": "influx, csv , ftp",
        "csv": {"enabled": True},
        "ftp": {"enabled": True, "host": "example.org"},
    }

    storage = StorageSettings.from_mapping(payload)

    assert storage.sinks == ["influx", "csv", "ftp"]


def test_csv_settings_reject_invalid_rotation():
    payload = {"enabled": True, "rotation": "hourly"}

    with pytest.raises(ValueError, match="csv.rotation"):
        CSVSinkSettings.from_mapping(payload)


def test_ftp_settings_require_positive_interval_when_provided():
    payload = {"enabled": True, "host": "example.org", "upload_interval_s": 0}

    with pytest.raises(ValueError, match="ftp.upload_interval_s debe ser > 0"):
        FTPSinkSettings.from_mapping(payload)

