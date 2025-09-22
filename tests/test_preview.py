import asyncio
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCR_PATH = ROOT / "edge" / "scr"
if str(SCR_PATH) not in sys.path:
    sys.path.append(str(SCR_PATH))

from acquisition import AcquisitionRunner, CalibratedBlock, CalibratedChannelBlock  # type: ignore  # noqa: E402
from edge.config.schema import (  # type: ignore  # noqa: E402
    AcquisitionSettings,
    Calibration,
    ChannelConfig,
    StationConfig,
    StorageSettings,
)
from preview import PreviewOptions, stream_preview  # type: ignore  # noqa: E402


def _make_station(total_samples: int = 4) -> StationConfig:
    acquisition = AcquisitionSettings(
        sample_rate_hz=10.0,
        block_size=2,
        duration_s=None,
        total_samples=total_samples,
    )
    channel = ChannelConfig(
        index=0,
        name="LVDT",
        unit="mm",
        voltage_range=10.0,
        calibration=Calibration(gain=2.0, offset=1.0),
    )
    return StationConfig(station_id="station", acquisition=acquisition, channels=[channel])


def _make_storage() -> StorageSettings:
    return StorageSettings(
        driver="influxdb_v2",
        url="http://example.com",
        org="org",
        bucket="bucket",
        token="token",
    )


def test_acquisition_runner_broadcasts_calibrated_blocks(monkeypatch):
    station = _make_station(total_samples=4)
    storage = _make_storage()
    queue: "asyncio.Queue[CalibratedBlock | None]" = asyncio.Queue()

    fake_board = object()
    monkeypatch.setattr("acquisition.open_mcc128", lambda: fake_board)

    def fake_start_scan(board, channels, fs_hz, channel_ranges=None, block_samples=None):
        assert board is fake_board
        return 0b1, block_samples or station.acquisition.block_size

    monkeypatch.setattr("acquisition.start_scan", fake_start_scan)

    blocks = [
        {0: [0.1, 0.2]},
        {0: [0.3, 0.4]},
    ]

    def fake_read_block(board, ch_mask, block_samples, channel_indices, sample_rate_hz=None):
        if blocks:
            return blocks.pop(0)
        return {ch: [] for ch in channel_indices}

    monkeypatch.setattr("acquisition.read_block", fake_read_block)

    sink_calls: list[str] = []

    def sink_factory(_storage):
        sink_calls.append("called")
        return []

    runner = AcquisitionRunner(
        station=station,
        storage=storage,
        sink_factory=sink_factory,
    )

    runner.run(mode="test", test_channel=queue)

    assert sink_calls == []
    assert runner._test_blocks_broadcast == 2
    assert runner._test_samples_broadcast == 4

    first_block = queue.get_nowait()
    assert isinstance(first_block, CalibratedBlock)
    assert first_block.channels[0].values == [1.2, 1.4]

    second_block = queue.get_nowait()
    assert isinstance(second_block, CalibratedBlock)
    assert second_block.channels[0].values == [1.6, 1.8]

    sentinel = queue.get_nowait()
    assert sentinel is None
    with pytest.raises(asyncio.QueueEmpty):
        queue.get_nowait()


async def _collect_preview(
    queue: "asyncio.Queue[CalibratedBlock | None]",
    station: StationConfig,
    options: PreviewOptions,
):
    payloads = []
    async for payload in stream_preview(queue, station, options=options):
        payloads.append(payload)
    return payloads


def test_stream_preview_downsamples_and_limits_duration():
    acquisition = AcquisitionSettings(sample_rate_hz=10.0, block_size=4)
    channels = [
        ChannelConfig(
            index=0,
            name="A",
            unit="mm",
            voltage_range=10.0,
            calibration=Calibration(gain=1.0, offset=0.0),
        ),
        ChannelConfig(
            index=1,
            name="B",
            unit="mm",
            voltage_range=10.0,
            calibration=Calibration(gain=1.0, offset=0.0),
        ),
    ]
    station = StationConfig(station_id="station", acquisition=acquisition, channels=channels)

    block = CalibratedBlock(
        station_id="station",
        timestamps_ns=[0, 1_000_000_000, 2_000_000_000, 3_000_000_000],
        channels={
            0: CalibratedChannelBlock(index=0, name="A", unit="mm", values=[0.0, 0.1, 0.2, 0.3]),
            1: CalibratedChannelBlock(index=1, name="B", unit="mm", values=[1.0, 1.1, 1.2, 1.3]),
        },
        captured_at_ns=123,
    )

    options = PreviewOptions(channels=[1], downsample=2, max_duration_s=2.0)

    async def _run_preview():
        queue: "asyncio.Queue[CalibratedBlock | None]" = asyncio.Queue()
        await queue.put(block)
        await queue.put(None)
        return await _collect_preview(queue, station, options)

    payloads = asyncio.run(_run_preview())

    assert len(payloads) == 1
    preview = payloads[0]
    assert preview["timestamps_ns"] == [0, 2_000_000_000]
    assert preview["channels"] == [
        {
            "index": 1,
            "name": "B",
            "unit": "mm",
            "values": [1.0, 1.2],
        }
    ]
