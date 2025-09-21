import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Allow importing scripts from the edge/scr directory.
SCR_PATH = ROOT / "edge" / "scr"
if str(SCR_PATH) not in sys.path:
    sys.path.append(str(SCR_PATH))

from edge.config import load_station_config  # type: ignore  # noqa: E402
from calibrate import apply_calibration  # type: ignore  # noqa: E402


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

    config_path = ROOT / "edge" / "config" / "sensors.yaml"
    station = load_station_config(config_path)

    assert station.channels, "No channels defined in sensors configuration"

    for channel in station.channels:
        value_gain = channel.calibration.gain
        value_offset = channel.calibration.offset
        for label, value in ("gain", value_gain), ("offset", value_offset):
            assert isinstance(value, (int, float)), f"{label} is not numeric: {value!r}"
            assert not math.isnan(value), f"{label} must not be NaN"
