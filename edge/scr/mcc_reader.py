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

DEFAULT_TIMEOUT_MARGIN_S = 0.5

def read_block(board, ch_mask, block_samples, channels, timeout=None, sample_rate_hz=None, safety_margin_s=DEFAULT_TIMEOUT_MARGIN_S):
    """Lee un bloque de muestras del MCC128.

    Si ``timeout`` no se provee, se calcula como la duración esperada del
    bloque (``block_samples / sample_rate_hz``) más un margen de seguridad
    ``safety_margin_s``. Esto evita un valor fijo que pudiera resultar muy
    corto cuando se cambia ``block_samples`` o la frecuencia de muestreo.
    """
    if timeout is None:
        if sample_rate_hz is None or sample_rate_hz <= 0:
            raise ValueError("Se requiere sample_rate_hz para calcular timeout dinámico")
        block_duration_s = block_samples / float(sample_rate_hz)
        timeout = block_duration_s + safety_margin_s

    data = board.a_in_scan_read(block_samples, timeout)
    if data.hardware_overrun or data.buffer_overrun:
        raise RuntimeError("Overrun de hardware/buffer")
    # data.data -> lista intercalada por canal
    # reacomoda a dict canal->lista
    out = {ch: [] for ch in channels}
    for i, val in enumerate(data.data):
        channel = channels[i % len(channels)]
        out[channel].append(val)
    return out
