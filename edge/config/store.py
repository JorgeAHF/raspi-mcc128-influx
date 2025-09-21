"""Helpers to load, validate and persist configuration files."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Mapping, Optional

import yaml

from .schema import StationConfig, StorageSettings

try:  # pragma: no cover - optional dependency available in production only
    from dotenv import dotenv_values
except Exception:  # pragma: no cover - keep optional to avoid hard dependency at runtime
    dotenv_values = None  # type: ignore[assignment]

CONFIG_DIR = Path(__file__).resolve().parent


def _read_yaml(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Expected a mapping at {path}, found {type(data).__name__}")
    return data


def _write_yaml(path: Path, payload: Mapping[str, Any]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)


def convert_legacy_station_payload(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Convert the pre-2.0 sensors.yaml layout into the new schema payload."""

    if "acquisition" in raw:
        return dict(raw)

    acquisition_payload: Dict[str, Any] = {
        "sample_rate_hz": raw.get("sample_rate_hz"),
        "scan_block_size": raw.get("scan_block_size"),
        "duration_s": raw.get("duration_s"),
        "total_samples": raw.get("total_samples"),
    }

    drift = raw.get("drift_detection")
    if isinstance(drift, Mapping):
        acquisition_payload["drift_detection"] = dict(drift)

    converted_channels = []
    for channel in raw.get("channels", []):
        if not isinstance(channel, Mapping):
            continue
        converted_channels.append(
            {
                "ch": channel.get("ch", channel.get("index")),
                "sensor": channel.get("sensor", channel.get("name")),
                "unit": channel.get("unit"),
                "v_range": channel.get("v_range", channel.get("voltage_range")),
                "calib": channel.get("calib", channel.get("calibration", {})),
            }
        )

    payload = {
        "station_id": raw.get("station_id"),
        "description": raw.get("description"),
        "acquisition": acquisition_payload,
        "channels": converted_channels,
    }
    return payload


def load_station_config(path: Optional[Path] = None) -> StationConfig:
    """Read and validate the station configuration from sensors.yaml."""

    cfg_path = path or CONFIG_DIR / "sensors.yaml"
    raw = _read_yaml(cfg_path)
    payload = convert_legacy_station_payload(raw)
    return StationConfig.from_mapping(payload)


def save_station_config(config: StationConfig, path: Optional[Path] = None):
    """Persist the station configuration using the canonical schema."""

    cfg_path = path or CONFIG_DIR / "sensors.yaml"
    payload = config.to_dict()
    _write_yaml(cfg_path, payload)


def load_storage_settings(path: Optional[Path] = None) -> StorageSettings:
    """Read and validate storage settings from storage.yaml."""

    cfg_path = path or CONFIG_DIR / "storage.yaml"
    raw = _read_yaml(cfg_path)
    return StorageSettings.from_mapping(raw)


def save_storage_settings(settings: StorageSettings, path: Optional[Path] = None):
    """Persist the storage settings to storage.yaml."""

    cfg_path = path or CONFIG_DIR / "storage.yaml"
    payload = settings.to_dict()
    _write_yaml(cfg_path, payload)


def storage_settings_from_env(env: Mapping[str, Any]) -> StorageSettings:
    """Create storage settings from environment variables."""

    retry_payload = {
        "max_attempts": env.get("INFLUX_RETRY_MAX_ATTEMPTS"),
        "base_delay_s": env.get("INFLUX_RETRY_BASE_DELAY_S"),
        "max_backoff_s": env.get("INFLUX_RETRY_MAX_BACKOFF_S"),
    }

    payload = {
        "driver": env.get("INFLUX_DRIVER", "influxdb_v2"),
        "url": env.get("INFLUX_URL"),
        "org": env.get("INFLUX_ORG"),
        "bucket": env.get("INFLUX_BUCKET"),
        "token": env.get("INFLUX_TOKEN"),
        "batch_size": env.get("INFLUX_BATCH_SIZE"),
        "timeout_s": env.get("INFLUX_TIMEOUT_S"),
        "queue_max_size": env.get("INFLUX_QUEUE_MAX_SIZE"),
        "retry": retry_payload,
    }
    verify_ssl = env.get("INFLUX_VERIFY_SSL", True)
    if isinstance(verify_ssl, str):
        verify_ssl = verify_ssl.strip().lower() not in {"0", "false", "no"}
    payload["verify_ssl"] = verify_ssl
    return StorageSettings.from_mapping(payload)


def default_storage_settings() -> StorageSettings:
    """Return a template storage configuration with placeholder values."""

    payload = {
        "driver": "influxdb_v2",
        "url": "http://localhost:8086",
        "org": "example-org",
        "bucket": "example-bucket",
        "token": "replace-with-real-token",
        "batch_size": 5,
        "timeout_s": 5.0,
        "queue_max_size": 1000,
        "verify_ssl": True,
        "retry": {
            "max_attempts": 5,
            "base_delay_s": 1.0,
            "max_backoff_s": 30.0,
        },
    }
    return StorageSettings.from_mapping(payload)


def load_env_file(path: Path) -> Mapping[str, str]:
    """Load key/value pairs from a dotenv file."""

    if dotenv_values is None:
        raise RuntimeError("python-dotenv is required to parse .env files")
    values = dotenv_values(str(path))  # type: ignore[operator]
    return {k: v for k, v in values.items() if v is not None}

