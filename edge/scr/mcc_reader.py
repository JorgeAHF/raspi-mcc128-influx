from daqhats import mcc128, OptionFlags, HatIDs, hat_list, AnalogInputMode, AnalogInputRange

def open_mcc128():
    hats = hat_list(HatIDs.MCC_128)
    if not hats: raise RuntimeError("No se encontró MCC128")
    return mcc128(hats[0].address)

def start_scan(board, channels, fs_hz, v_range=AnalogInputRange.BIP_10V, block_samples=1000):
    ch_mask = 0
    for ch in channels: ch_mask |= 1 << ch
    board.a_in_mode_write(AnalogInputMode.DIFFERENTIAL)  # usa DIFF si tu cableado lo permite
    board.a_in_range_write(v_range)
    board.a_in_scan_start(
        channel_mask=ch_mask,
        samples_per_channel=0,               # 0 = continuo
        sample_rate_per_channel=fs_hz,
        options=OptionFlags.CONTINUOUS
    )
    return ch_mask, block_samples

def read_block(board, ch_mask, block_samples, num_ch):
    data = board.a_in_scan_read(block_samples, 5.0)  # timeout 5s
    if data.hardware_overrun or data.buffer_overrun:
        raise RuntimeError("Overrun de hardware/buffer")
    # data.data -> lista intercalada por canal
    # reacomoda a dict canal->lista
    out = {ch: [] for ch in range(8)}
    for i, val in enumerate(data.data):
        ch = i % num_ch
        out[ch].append(val)
    return out
