import logging
import sys
from pathlib import Path

# Ensure the repository root (edge parent) is importable when executed as script.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.config.schema import StationConfig, StorageSettings
from edge.config.store import load_station_config, load_storage_settings

from acquisition import AcquisitionBlock, AcquisitionRunner, _consume_block_timestamps
from calibrate import apply_calibration
from sender import InfluxSender, to_line


logger = logging.getLogger(__name__)


def _build_block_handler(station_cfg: StationConfig, sender: InfluxSender):
    pi = station_cfg.station_id
    channels = station_cfg.channels
    indices = [c.index for c in channels]
    metadata = {
        ch.index: (ch.name, ch.unit, ch.calibration.gain, ch.calibration.offset)
        for ch in channels
    }

    def handle_block(block: AcquisitionBlock) -> None:
        timestamps = block.timestamps_ns
        for ch in indices:
            sensor, unit, gain, offset = metadata[ch]
            values = apply_calibration(block.values_by_channel.get(ch, []), gain, offset)
            for ts_ns, mm in zip(timestamps, values):
                line = to_line(
                    "lvdt",
                    tags={"pi": pi, "canal": ch, "sensor": sensor, "unidad": unit},
                    fields={"valor": float(mm)},
                    ts_ns=ts_ns,
                )
                sender.enqueue(line)

    return handle_block


def main(station: StationConfig | None = None, storage: StorageSettings | None = None):
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    station_cfg = station or load_station_config()
    storage_cfg = storage or load_storage_settings()

    sender = InfluxSender(storage_cfg)
    try:
        handler = _build_block_handler(station_cfg, sender)
        runner = AcquisitionRunner(
            settings=station_cfg.acquisition,
            channels=station_cfg.channels,
            on_block=handler,
        )
        has_limits = (
            station_cfg.acquisition.duration_s is not None
            or station_cfg.acquisition.total_samples is not None
        )
        mode = "timed" if has_limits else "continuous"
        runner.run(mode=mode)
    except KeyboardInterrupt:
        logger.info("Adquisición interrumpida por el usuario.")
    finally:
        sender.close()


if __name__ == "__main__":
    main()
