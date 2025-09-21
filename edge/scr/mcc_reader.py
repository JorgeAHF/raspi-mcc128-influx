"""Helpers to interface with the MCC128 DAQ board."""

from __future__ import annotations

from typing import Mapping, Sequence

from daqhats import (
    AnalogInputMode,
    AnalogInputRange,
    HatIDs,
    OptionFlags,
    hat_list,
    mcc128,
)

RANGE_MAP = {
    10.0: AnalogInputRange.BIP_10V,
    5.0: AnalogInputRange.BIP_5V,
    2.0: AnalogInputRange.BIP_2V,
    1.0: AnalogInputRange.BIP_1V,
}


def open_mcc128():
    hats = hat_list(HatIDs.MCC_128)
    if not hats:
        raise RuntimeError("No se encontró MCC128")
    return mcc128(hats[0].address)


def _coerce_voltage_range(value: float | AnalogInputRange) -> AnalogInputRange:
    if isinstance(value, AnalogInputRange):
        return value
    mapped = RANGE_MAP.get(round(float(value), 6))
    if mapped is None:
        raise ValueError(
            f"Rango de voltaje {value!r} no soportado; valores válidos: {sorted(RANGE_MAP)}"
        )
    return mapped


def resolve_input_range(
    channel_ranges: Mapping[int, float | AnalogInputRange] | Sequence[float | AnalogInputRange] | None,
    *,
    default: AnalogInputRange = AnalogInputRange.BIP_10V,
) -> AnalogInputRange:
    """Resolve the AnalogInputRange to apply to the MCC128 scan.

    The MCC128 applies the same voltage range to every enabled channel. When
    the configuration requests different ranges the function raises a
    ValueError, documenting the hardware limitation to avoid silent
    misconfigurations.
    """

    if not channel_ranges:
        return default

    if isinstance(channel_ranges, Mapping):
        requested = [_coerce_voltage_range(value) for value in channel_ranges.values()]
    else:
        requested = [_coerce_voltage_range(value) for value in channel_ranges]

    unique = {item for item in requested}
    if not unique:
        return default
    if len(unique) > 1:
        raise ValueError(
            "MCC128 solo admite un rango de entrada global; se recibieron múltiples valores: "
            + ", ".join(sorted({rng.name for rng in unique}))
        )
    return unique.pop()


def start_scan(
    board,
    channels: Sequence[int],
    fs_hz: float,
    *,
    channel_ranges: Mapping[int, float | AnalogInputRange] | Sequence[float | AnalogInputRange] | None = None,
    block_samples: int = 1000,
):
    ch_mask = 0
    for ch in channels:
        ch_mask |= 1 << ch
    board.a_in_mode_write(AnalogInputMode.DIFFERENTIAL)
    board.a_in_range_write(resolve_input_range(channel_ranges))
    board.a_in_scan_start(
        channel_mask=ch_mask,
        samples_per_channel=0,
        sample_rate_per_channel=fs_hz,
        options=OptionFlags.CONTINUOUS,
    )
    return ch_mask, block_samples


DEFAULT_TIMEOUT_MARGIN_S = 0.5


def read_block(
    board,
    ch_mask,
    block_samples,
    channels,
    timeout=None,
    sample_rate_hz=None,
    safety_margin_s=DEFAULT_TIMEOUT_MARGIN_S,
):
    """Lee un bloque de muestras del MCC128."""

    if timeout is None:
        if sample_rate_hz is None or sample_rate_hz <= 0:
            raise ValueError("Se requiere sample_rate_hz para calcular timeout dinámico")
        block_duration_s = block_samples / float(sample_rate_hz)
        timeout = block_duration_s + safety_margin_s

    data = board.a_in_scan_read(block_samples, timeout)
    if data.hardware_overrun or data.buffer_overrun:
        raise RuntimeError("Overrun de hardware/buffer")
    out = {ch: [] for ch in channels}
    for i, val in enumerate(data.data):
        channel = channels[i % len(channels)]
        out[channel].append(val)
    return out
