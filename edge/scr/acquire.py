import os, time
import yaml
from time import time_ns
from daqhats import AnalogInputRange
from mcc_reader import open_mcc128, start_scan, read_block, DEFAULT_TIMEOUT_MARGIN_S
from calibrate import apply_calibration
from sender import InfluxSender, to_line

def main():
    cfg = yaml.safe_load(open("config/sensors.yaml","r"))
    pi = cfg["station_id"]
    fs = cfg["sample_rate_hz"]
    chans = [c["ch"] for c in cfg["channels"]]
    board = open_mcc128()
    ch_mask, block = start_scan(board, chans, fs, AnalogInputRange.BIP_10V, cfg.get("scan_block_size", 1000))
    sender = InfluxSender()
    map_cal = {c["ch"]:(c["sensor"], c["unit"], c["calib"]["gain"], c["calib"]["offset"]) for c in cfg["channels"]}

    ts_step = int(1e9 / fs)

    block_duration_s = block / float(fs) if fs else 0.0
    timeout_s = block_duration_s + DEFAULT_TIMEOUT_MARGIN_S

    while True:
        raw = read_block(board, ch_mask, block, chans, timeout=timeout_s)
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

if __name__ == "__main__":
    main()
