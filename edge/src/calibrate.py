def apply_calibration(volts_list, gain, offset):
    # mm = gain*V + offset
    return [gain*v + offset for v in volts_list]
