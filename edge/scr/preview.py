"""Async helpers to consume calibrated blocks and expose preview payloads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import AsyncIterator, Iterable, List, Optional, Sequence

from edge.config.schema import ChannelConfig, StationConfig

from .acquisition import CalibratedBlock, CalibratedChannelBlock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreviewOptions:
    """Runtime configuration for preview streaming."""

    channels: Optional[Sequence[int]] = None
    max_duration_s: Optional[float] = None
    downsample: int = 1

    def normalized_downsample(self) -> int:
        step = int(self.downsample) if self.downsample is not None else 1
        if step < 1:
            logger.warning("Downsample <1 (%s) recibido; se ajusta a 1.", step)
            return 1
        return step


def _ack_queue(queue: asyncio.Queue[Optional[CalibratedBlock]]) -> None:
    task_done = getattr(queue, "task_done", None)
    if callable(task_done):  # pragma: no branch - simple guard
        try:
            task_done()
        except ValueError:  # pragma: no cover - join() not in use
            pass


def _select_channels(station: StationConfig, requested: Optional[Sequence[int]]) -> List[ChannelConfig]:
    if not requested:
        return list(station.channels)
    mapping = {channel.index: channel for channel in station.channels}
    selected: List[ChannelConfig] = []
    seen = set()
    for raw_idx in requested:
        idx = int(raw_idx)
        if idx in seen:
            continue
        seen.add(idx)
        if idx not in mapping:
            raise ValueError(f"Canal {idx} no está configurado en la estación")
        selected.append(mapping[idx])
    return selected


def _filter_block(
    block: CalibratedBlock,
    channels: Iterable[ChannelConfig],
    *,
    downsample: int,
) -> Optional[tuple[List[int], List[CalibratedChannelBlock]]]:
    timestamps = block.timestamps_ns[::downsample]
    if not timestamps:
        return None
    selected_channels: List[CalibratedChannelBlock] = []
    for channel_cfg in channels:
        channel_data = block.channels.get(channel_cfg.index)
        if channel_data is None:
            continue
        values = channel_data.values[::downsample]
        if not values:
            continue
        selected_channels.append(
            CalibratedChannelBlock(
                index=channel_data.index,
                name=channel_data.name,
                unit=channel_data.unit,
                values=values,
            )
        )
    if not selected_channels:
        return None
    return timestamps, selected_channels


async def stream_preview(
    queue: "asyncio.Queue[Optional[CalibratedBlock]]",
    station: StationConfig,
    *,
    options: Optional[PreviewOptions] = None,
) -> AsyncIterator[dict]:
    """Yield preview payloads until the queue provides a sentinel or duration limit."""

    opts = options or PreviewOptions()
    if opts.max_duration_s is not None and opts.max_duration_s <= 0:
        raise ValueError("max_duration_s debe ser > 0")

    downsample = opts.normalized_downsample()
    selected_channels = _select_channels(station, opts.channels)

    start_ts_ns: Optional[int] = None
    delivered_duration_ns = 0

    while True:
        block = await queue.get()
        try:
            if block is None:
                logger.debug("Cola de vista previa recibió señal de cierre.")
                break

            filtered = _filter_block(block, selected_channels, downsample=downsample)
            if filtered is None:
                continue
            timestamps, channels_payload = filtered
            payload = {
                "station_id": block.station_id,
                "captured_at_ns": block.captured_at_ns,
                "timestamps_ns": timestamps,
                "channels": [
                    {
                        "index": channel.index,
                        "name": channel.name,
                        "unit": channel.unit,
                        "values": channel.values,
                    }
                    for channel in channels_payload
                ],
            }
            yield payload

            if opts.max_duration_s is not None:
                if start_ts_ns is None:
                    start_ts_ns = timestamps[0]
                delivered_duration_ns = timestamps[-1] - start_ts_ns
                if delivered_duration_ns >= opts.max_duration_s * 1e9:
                    logger.info(
                        "Duración máxima de vista previa alcanzada (%.2f s); se detiene el stream.",
                        opts.max_duration_s,
                    )
                    break
        finally:
            _ack_queue(queue)

    logger.debug(
        "Stream de vista previa finalizado tras %.3f s y downsample=%d.",
        delivered_duration_ns / 1e9 if delivered_duration_ns else 0.0,
        downsample,
    )
