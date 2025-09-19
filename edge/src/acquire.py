import sys
from pathlib import Path
from time import time_ns

import yaml
from daqhats import AnalogInputRange

if __package__ is None or __package__ == "":
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from edge.src.calibrate import apply_calibration
from edge.src.mcc_reader import (
    DEFAULT_TIMEOUT_MARGIN_S,
    open_mcc128,
    read_block,
    start_scan,
)
from edge.src.sender import InfluxSender, to_line

def main():
    cfg = yaml.safe_load(open("config/sensors.yaml","r"))
    pi = cfg["station_id"]
    fs = cfg["sample_rate_hz"]
    chans = [c["ch"] for c in cfg["channels"]]
    board = None
    sender = None
    try:
        board = open_mcc128()
        ch_mask, block = start_scan(board, chans, fs, AnalogInputRange.BIP_10V, cfg.get("scan_block_size", 1000))
        sender = InfluxSender()
        map_cal = {c["ch"]:(c["sensor"], c["unit"], c["calib"]["gain"], c["calib"]["offset"]) for c in cfg["channels"]}

        ts_step = int(1e9 / fs)

        while True:
            raw = read_block(board, ch_mask, block, chans, sample_rate_hz=fs)
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
            stop_scan = getattr(board, "a_in_scan_stop", None)
            if callable(stop_scan):
                stop_scan()
            cleanup_scan = getattr(board, "a_in_scan_cleanup", None)
            if callable(cleanup_scan):
                cleanup_scan()

if __name__ == "__main__":
    main()
