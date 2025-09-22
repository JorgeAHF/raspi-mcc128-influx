import logging
import sys
from pathlib import Path

# Ensure the repository root (edge parent) is importable when executed as script.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.config.schema import StationConfig, StorageSettings
from edge.config.store import load_station_config, load_storage_settings

from acquisition import AcquisitionRunner, _consume_block_timestamps

__all__ = [
    "main",
    "_consume_block_timestamps",
]


logger = logging.getLogger(__name__)
def main(station: StationConfig | None = None, storage: StorageSettings | None = None):
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    station_cfg = station or load_station_config()
    storage_cfg = storage or load_storage_settings()

    try:
        runner = AcquisitionRunner(
            station=station_cfg,
            storage=storage_cfg,
        )
        has_limits = (
            station_cfg.acquisition.duration_s is not None
            or station_cfg.acquisition.total_samples is not None
        )
        mode = "timed" if has_limits else "continuous"
        runner.run(mode=mode)
    except KeyboardInterrupt:
        logger.info("Adquisición interrumpida por el usuario.")


if __name__ == "__main__":
    main()
