import logging
from time import time_ns

import yaml
from daqhats import AnalogInputRange

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

def main():
    if not logging.getLogger().hasHandlers():
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = yaml.safe_load(open("config/sensors.yaml", "r"))
    pi = cfg["station_id"]
    fs = cfg["sample_rate_hz"]
    chans = [c["ch"] for c in cfg["channels"]]
    board = None
    sender = None
    try:
        board = open_mcc128()
        ch_mask, block = start_scan(board, chans, fs, AnalogInputRange.BIP_10V, cfg.get("scan_block_size", 1000))
        sender = InfluxSender()
        map_cal = {
            c["ch"]: (c["sensor"], c["unit"], c["calib"]["gain"], c["calib"]["offset"])
            for c in cfg["channels"]
        }

        ts_step = int(1e9 / fs)
        next_ts_ns = time_ns()
        drift_cfg = cfg.get("drift_detection") or {}
        drift_threshold_ns = None
        if isinstance(drift_cfg, dict):
            threshold_value = drift_cfg.get("correction_threshold_ns")
            if threshold_value is not None:
                drift_threshold_ns = int(threshold_value)

        while True:
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
