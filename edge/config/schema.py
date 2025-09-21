"""Typed configuration models implemented with dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _as_str(value: Any, field_name: str, *, optional: bool = False) -> Optional[str]:
    if value is None:
        if optional:
            return None
        raise ValueError(f"'{field_name}' es obligatorio")
    text = str(value).strip()
    if not text and not optional:
        raise ValueError(f"'{field_name}' no puede estar vacío")
    return text or None


def _as_int(value: Any, field_name: str) -> int:
    if value is None:
        raise ValueError(f"'{field_name}' es obligatorio")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"'{field_name}' debe ser un entero válido") from exc
    return result


def _as_float(value: Any, field_name: str) -> float:
    if value is None:
        raise ValueError(f"'{field_name}' es obligatorio")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
        raise ValueError(f"'{field_name}' debe ser numérico") from exc
    return result


def _as_optional_float(value: Any, field_name: str) -> Optional[float]:
    if value is None or value == "":
        return None
    result = _as_float(value, field_name)
    return result


def _as_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "si", "sí"}:
        return True
    if text in {"0", "false", "no"}:
        return False
    return default


@dataclass
class Calibration:
    gain: float = 1.0
    offset: float = 0.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "Calibration":
        if not data:
            return cls()
        gain = _as_float(data.get("gain", 1.0), "calibration.gain")
        offset = _as_float(data.get("offset", 0.0), "calibration.offset")
        return cls(gain=gain, offset=offset)

    def to_dict(self) -> Dict[str, float]:
        return {"gain": self.gain, "offset": self.offset}


@dataclass
class DriftDetectionSettings:
    correction_threshold_ns: Optional[int] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "DriftDetectionSettings":
        if not data:
            return cls()
        threshold_raw = data.get("correction_threshold_ns")
        if threshold_raw is None or threshold_raw == "":
            return cls()
        threshold = _as_int(threshold_raw, "drift_detection.correction_threshold_ns")
        if threshold < 0:
            raise ValueError("drift_detection.correction_threshold_ns debe ser >= 0")
        return cls(correction_threshold_ns=threshold)

    def to_dict(self) -> Dict[str, Optional[int]]:
        return {"correction_threshold_ns": self.correction_threshold_ns}


@dataclass
class AcquisitionSettings:
    sample_rate_hz: float
    block_size: int = 1000
    duration_s: Optional[float] = None
    total_samples: Optional[int] = None
    drift_detection: DriftDetectionSettings = field(default_factory=DriftDetectionSettings)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AcquisitionSettings":
        sample_rate = _as_float(data.get("sample_rate_hz"), "sample_rate_hz")
        if sample_rate <= 0:
            raise ValueError("sample_rate_hz debe ser > 0")

        block_raw = data.get("block_size", data.get("scan_block_size", 1000))
        block_size = _as_int(block_raw, "block_size")
        if block_size <= 0:
            raise ValueError("block_size debe ser > 0")

        duration = _as_optional_float(data.get("duration_s"), "duration_s")
        if duration is not None and duration <= 0:
            raise ValueError("duration_s debe ser > 0")

        samples_raw = data.get("total_samples")
        if samples_raw is None or samples_raw == "":
            total_samples = None
        else:
            total_samples = _as_int(samples_raw, "total_samples")
            if total_samples <= 0:
                raise ValueError("total_samples debe ser > 0")

        drift = DriftDetectionSettings.from_mapping(data.get("drift_detection"))
        return cls(
            sample_rate_hz=sample_rate,
            block_size=block_size,
            duration_s=duration,
            total_samples=total_samples,
            drift_detection=drift,
        )

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "sample_rate_hz": self.sample_rate_hz,
            "block_size": self.block_size,
            "duration_s": self.duration_s,
            "total_samples": self.total_samples,
            "drift_detection": self.drift_detection.to_dict(),
        }
        return payload


@dataclass
class ChannelConfig:
    index: int
    name: str
    unit: str
    voltage_range: float
    calibration: Calibration = field(default_factory=Calibration)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "ChannelConfig":
        index = _as_int(data.get("index", data.get("ch")), "channels[].index")
        if index < 0:
            raise ValueError("channels[].index debe ser >= 0")
        name = _as_str(data.get("name", data.get("sensor")), "channels[].name")
        unit = _as_str(data.get("unit"), "channels[].unit")
        voltage = _as_float(data.get("voltage_range", data.get("v_range")), "channels[].voltage_range")
        if voltage <= 0:
            raise ValueError("channels[].voltage_range debe ser > 0")
        calibration = Calibration.from_mapping(data.get("calibration") or data.get("calib"))
        return cls(index=index, name=name, unit=unit, voltage_range=voltage, calibration=calibration)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "name": self.name,
            "unit": self.unit,
            "voltage_range": self.voltage_range,
            "calibration": self.calibration.to_dict(),
        }


@dataclass
class StationConfig:
    station_id: str
    acquisition: AcquisitionSettings
    channels: List[ChannelConfig] = field(default_factory=list)
    description: Optional[str] = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StationConfig":
        station_id = _as_str(data.get("station_id"), "station_id")
        description = _as_str(data.get("description"), "description", optional=True)
        acquisition_payload = data.get("acquisition")
        if not isinstance(acquisition_payload, Mapping):
            raise ValueError("El bloque 'acquisition' es obligatorio")
        acquisition = AcquisitionSettings.from_mapping(acquisition_payload)
        channels_payload = data.get("channels") or []
        if not isinstance(channels_payload, Iterable):
            raise ValueError("channels debe ser una lista")
        channels = [ChannelConfig.from_mapping(ch) for ch in channels_payload]
        seen = set()
        for channel in channels:
            if channel.index in seen:
                raise ValueError(f"canal duplicado: {channel.index}")
            seen.add(channel.index)
        return cls(station_id=station_id, acquisition=acquisition, channels=channels, description=description)

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "station_id": self.station_id,
            "acquisition": self.acquisition.to_dict(),
            "channels": [ch.to_dict() for ch in self.channels],
        }
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass
class RetrySettings:
    max_attempts: int = 5
    base_delay_s: float = 1.0
    max_backoff_s: Optional[float] = 30.0

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "RetrySettings":
        if not data:
            return cls()
        max_attempts = _as_int(data.get("max_attempts", 5), "retry.max_attempts")
        if max_attempts < 1:
            raise ValueError("retry.max_attempts debe ser >= 1")
        base_delay = _as_float(data.get("base_delay_s", 1.0), "retry.base_delay_s")
        if base_delay < 0:
            raise ValueError("retry.base_delay_s debe ser >= 0")
        max_backoff_raw = data.get("max_backoff_s", 30.0)
        max_backoff = _as_optional_float(max_backoff_raw, "retry.max_backoff_s")
        if max_backoff is not None and max_backoff < 0:
            raise ValueError("retry.max_backoff_s debe ser >= 0")
        return cls(max_attempts=max_attempts, base_delay_s=base_delay, max_backoff_s=max_backoff)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "base_delay_s": self.base_delay_s,
            "max_backoff_s": self.max_backoff_s,
        }


@dataclass
class StorageSettings:
    driver: str
    url: str
    org: str
    bucket: str
    token: str
    batch_size: int = 5
    timeout_s: float = 5.0
    queue_max_size: int = 1000
    verify_ssl: bool = True
    retry: RetrySettings = field(default_factory=RetrySettings)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "StorageSettings":
        driver = _as_str(data.get("driver", "influxdb_v2"), "driver") or "influxdb_v2"
        url = _as_str(data.get("url"), "url")
        org = _as_str(data.get("org"), "org")
        bucket = _as_str(data.get("bucket"), "bucket")
        token = _as_str(data.get("token"), "token")
        batch_size = _as_int(data.get("batch_size", 5), "batch_size")
        if batch_size < 1:
            raise ValueError("batch_size debe ser >= 1")
        timeout_s = _as_float(data.get("timeout_s", 5.0), "timeout_s")
        if timeout_s <= 0:
            raise ValueError("timeout_s debe ser > 0")
        queue_max_size = _as_int(data.get("queue_max_size", 1000), "queue_max_size")
        if queue_max_size < 1:
            raise ValueError("queue_max_size debe ser >= 1")
        verify_ssl = _as_bool(data.get("verify_ssl"), True)
        retry = RetrySettings.from_mapping(data.get("retry"))
        return cls(
            driver=driver,
            url=url,
            org=org,
            bucket=bucket,
            token=token,
            batch_size=batch_size,
            timeout_s=timeout_s,
            queue_max_size=queue_max_size,
            verify_ssl=verify_ssl,
            retry=retry,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "driver": self.driver,
            "url": self.url,
            "org": self.org,
            "bucket": self.bucket,
            "token": self.token,
            "batch_size": self.batch_size,
            "timeout_s": self.timeout_s,
            "queue_max_size": self.queue_max_size,
            "verify_ssl": self.verify_ssl,
            "retry": self.retry.to_dict(),
        }

