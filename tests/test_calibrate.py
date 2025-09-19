import math
import sys
from pathlib import Path

import pytest
import yaml

sys.path.append(str(Path(__file__).resolve().parents[1]))

from edge.src.calibrate import apply_calibration


@pytest.mark.parametrize(
    "voltages, gain, offset, expected",
    [
        ([0.0, 0.5, 1.0], 2.0, 0.0, [0.0, 1.0, 2.0]),
        ([-1.0, 0.0, 1.0], 1.5, -0.2, [-1.7, -0.2, 1.3]),
        ([-0.5, 0.5], -1.0, 0.1, [0.6, -0.4]),
    ],
)
def test_apply_calibration_varied_inputs(voltages, gain, offset, expected):
    """apply_calibration should handle positive/negative values and offsets."""

    calibrated = apply_calibration(voltages, gain, offset)

    assert calibrated == pytest.approx(expected)


def test_sensor_calibration_entries_are_numeric():
    """Each configured channel must define numeric gain and offset values."""

    config_path = Path(__file__).resolve().parents[1] / "edge" / "config" / "sensors.yaml"
    with config_path.open("r", encoding="utf-8") as f:
        sensors_config = yaml.safe_load(f)

    channels = sensors_config.get("channels", [])
    assert channels, "No channels defined in sensors configuration"

    for channel in channels:
        calib = channel.get("calib")
        assert isinstance(calib, dict), f"Channel {channel} missing calibration info"

        for key in ("gain", "offset"):
            assert key in calib, f"Calibration entry missing '{key}'"
            value = calib[key]
            assert isinstance(value, (int, float)), f"{key} is not numeric: {value!r}"
            assert not math.isnan(value), f"{key} must not be NaN"
