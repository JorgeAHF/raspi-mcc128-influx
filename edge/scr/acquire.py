import os, time
import yaml
from time import time_ns
from daqhats import AnalogInputRange
from mcc_reader import open_mcc128, start_scan, read_block
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
    num_ch = len(chans)
    map_cal = {c["ch"]:(c["sensor"], c["unit"], c["calib"]["gain"], c["calib"]["offset"]) for c in cfg["channels"]}

    while True:
        raw = read_block(board, ch_mask, block, num_ch)
        now_ns = time_ns()
        # para cada canal, aplica calibración y envía cada muestra
        for ch in chans:
            sensor, unit, gain, offset = map_cal[ch]
            vals = apply_calibration(raw[ch], gain, offset)
            # empaqueta por muestra (si el volumen es alto, agrega por estadísticos por bloque)
            ts_step = int(1e9 / fs)
            ts0 = now_ns - ts_step*(len(vals)-1)
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
