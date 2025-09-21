import logging
import sys
from pathlib import Path
from time import time_ns

from daqhats import AnalogInputRange

# Ensure the repository root (edge parent) is importable when executed as script.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from edge.config.store import load_station_config, load_storage_settings
from edge.config.schema import StationConfig, StorageSettings

from calibrate import apply_calibration
from mcc_reader import open_mcc128, read_block, start_scan
from sender import InfluxSender, to_line


logger = logging.getLogger(__name__)


def _consume_block_timestamps(next_ts_ns: int, block_len: int, ts_step: int):
    """Return timestamps for a block and the updated accumulator.

    Parameters
    ----------
    next_ts_ns:
        Timestamp assigned to the first sample in the block.
    block_len:
        Number of samples in the block.
    ts_step:
        Nanoseconds between consecutive samples.

    Returns
    -------
    tuple[list[int], int]
        The list of timestamps for each sample and the accumulator
        advanced by ``block_len`` steps.
    """

    timestamps = [next_ts_ns + i * ts_step for i in range(block_len)]
    return timestamps, next_ts_ns + block_len * ts_step

RANGE_MAP = {
    10.0: AnalogInputRange.BIP_10V,
    5.0: AnalogInputRange.BIP_5V,
    2.0: AnalogInputRange.BIP_2V,
    1.0: AnalogInputRange.BIP_1V,
}


def _select_input_range(config: StationConfig) -> AnalogInputRange:
    if not config.channels:
        return AnalogInputRange.BIP_10V
    ranges = {round(float(ch.voltage_range), 6) for ch in config.channels if ch.voltage_range}
    if not ranges:
        return AnalogInputRange.BIP_10V
    if len(ranges) > 1:
        logger.warning(
            "Se configuraron múltiples rangos de voltaje %s; se usará el mayor disponible.",
            sorted(ranges),
        )
    for value in sorted(ranges, reverse=True):
        mapped = RANGE_MAP.get(value)
        if mapped is not None:
            return mapped
    logger.warning(
        "No se reconocen los rangos %s; se usará ±10 V por defecto.",
        sorted(ranges),
    )
    return AnalogInputRange.BIP_10V


def main(station: StationConfig | None = None, storage: StorageSettings | None = None):
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    station_cfg = station or load_station_config()
    storage_cfg = storage or load_storage_settings()

    pi = station_cfg.station_id
    fs = station_cfg.acquisition.sample_rate_hz
    chans = [c.index for c in station_cfg.channels]
    block_size = station_cfg.acquisition.block_size
    drift_cfg = station_cfg.acquisition.drift_detection
    board = None
    sender = None
    try:
        board = open_mcc128()
        ch_mask, block = start_scan(board, chans, fs, _select_input_range(station_cfg), block_size)
        sender = InfluxSender(storage_cfg)
        map_cal = {
            ch.index: (ch.name, ch.unit, ch.calibration.gain, ch.calibration.offset)
            for ch in station_cfg.channels
        }

        ts_step = int(1e9 / fs)
        next_ts_ns = time_ns()
        drift_threshold_ns = None
        if drift_cfg.correction_threshold_ns is not None:
            drift_threshold_ns = int(drift_cfg.correction_threshold_ns)

        acquisition_deadline_ns = None
        if station_cfg.acquisition.duration_s is not None:
            acquisition_deadline_ns = next_ts_ns + int(station_cfg.acquisition.duration_s * 1e9)

        while True:
            if acquisition_deadline_ns is not None and time_ns() >= acquisition_deadline_ns:
                logger.info("Duración de adquisición alcanzada; deteniendo la captura.")
                break
            raw = read_block(board, ch_mask, block, chans, sample_rate_hz=fs)
            block_captured_ns = time_ns()
            block_len = len(raw[chans[0]]) if chans else 0
            if block_len == 0:
                continue

            timestamps, candidate_next_ts_ns = _consume_block_timestamps(next_ts_ns, block_len, ts_step)

            # para cada canal, aplica calibración y envía cada muestra
            for ch in chans:
                sensor, unit, gain, offset = map_cal[ch]
                vals = apply_calibration(raw[ch], gain, offset)
                # empaqueta por muestra (si el volumen es alto, agrega por estadísticos por bloque)
                for ts_ns, mm in zip(timestamps, vals):
                    line = to_line(
                        "lvdt",
                        tags={"pi": pi, "canal": ch, "sensor": sensor, "unidad": unit},
                        fields={"valor": float(mm)},
                        ts_ns=ts_ns,
                    )
                    sender.enqueue(line)

            expected_next_ts_ns = block_captured_ns + ts_step
            drift_ns = expected_next_ts_ns - candidate_next_ts_ns
            abs_drift_ns = abs(drift_ns)

            if drift_threshold_ns is not None and abs_drift_ns > drift_threshold_ns:
                logger.debug(
                    "Deriva detectada tras bloque de %d muestras: ajuste %+d ns (%.3f ms)",
                    block_len,
                    drift_ns,
                    drift_ns / 1e6,
                )
                next_ts_ns = expected_next_ts_ns
            else:
                next_ts_ns = candidate_next_ts_ns

            logger.info(
                "Bloque con %d muestras; desviación máxima %.3f ms (%d ns)",
                block_len,
                abs_drift_ns / 1e6,
                abs_drift_ns,
            )
            if acquisition_deadline_ns is not None and block_captured_ns >= acquisition_deadline_ns:
                logger.info("Duración de adquisición alcanzada tras enviar el bloque actual.")
                break
    except KeyboardInterrupt:
        pass
    finally:
        if sender is not None:
            sender.close()
        if board is not None:
            stop_scan = getattr(board, "a_in_scan_stop", None)
            if callable(stop_scan):
                stop_scan()
            cleanup_scan = getattr(board, "a_in_scan_cleanup", None)
            if callable(cleanup_scan):
                cleanup_scan()

if __name__ == "__main__":
    main()
