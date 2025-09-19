import time
import logging
import yaml
from time import time_ns
from daqhats import AnalogInputRange
from mcc_reader import open_mcc128, start_scan, read_block
from calibrate import apply_calibration
from sender import InfluxSender, to_line


logger = logging.getLogger(__name__)


def _stop_and_cleanup(board):
    if board is None:
        return
    stop_scan = getattr(board, "a_in_scan_stop", None)
    if callable(stop_scan):
        stop_scan()
    cleanup_scan = getattr(board, "a_in_scan_cleanup", None)
    if callable(cleanup_scan):
        cleanup_scan()

def main():
    cfg = yaml.safe_load(open("config/sensors.yaml","r"))
    pi = cfg["station_id"]
    fs = cfg["sample_rate_hz"]
    chans = [c["ch"] for c in cfg["channels"]]
    board = None
    sender = None
    try:
        board = open_mcc128()
        block = cfg.get("scan_block_size", 1000)
        ch_mask, block = start_scan(board, chans, fs, AnalogInputRange.BIP_10V, block)
        sender = InfluxSender()
        map_cal = {c["ch"]:(c["sensor"], c["unit"], c["calib"]["gain"], c["calib"]["offset"]) for c in cfg["channels"]}

        ts_step = int(1e9 / fs)
        retry_backoff_s = cfg.get("scan_retry_backoff_s", 5)
        max_retries = cfg.get("scan_max_retries", 3)
        retry_count = 0

        while True:
            try:
                raw = read_block(board, ch_mask, block, chans, sample_rate_hz=fs)
                retry_count = 0
            except RuntimeError as exc:
                retry_count += 1
                logger.warning(
                    "Fallo en read_block (intento %s/%s): %s",
                    retry_count,
                    max_retries,
                    exc,
                )
                _stop_and_cleanup(board)
                time.sleep(retry_backoff_s)
                if retry_count > max_retries:
                    logger.error(
                        "Se superó el máximo de reintentos (%s); reabriendo MCC128.",
                        max_retries,
                    )
                    close_board = getattr(board, "close", None)
                    if callable(close_board):
                        close_board()
                    board = open_mcc128()
                ch_mask, block = start_scan(board, chans, fs, AnalogInputRange.BIP_10V, block)
                continue
            now_ns = time_ns()
            block_len = len(raw[chans[0]]) if chans else 0
            if block_len == 0:
                continue
            ts0 = now_ns - ts_step * (block_len - 1)
            # para cada canal, aplica calibración y envía cada muestra
            for ch in chans:
                sensor, unit, gain, offset = map_cal[ch]
                vals = apply_calibration(raw[ch], gain, offset)
                # empaqueta por muestra (si el volumen es alto, agrega por estadísticos por bloque)
                for i, mm in enumerate(vals):
                    line = to_line(
                        "lvdt",
                        tags={"pi":pi, "canal":ch, "sensor":sensor, "unidad":unit},
                        fields={"valor":float(mm)},
                        ts_ns=ts0 + i*ts_step
                    )
                    sender.enqueue(line)
    except KeyboardInterrupt:
        pass
    finally:
        if sender is not None:
            sender.close()
        if board is not None:
            _stop_and_cleanup(board)

if __name__ == "__main__":
    main()
