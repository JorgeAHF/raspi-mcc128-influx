import logging
import os
import subprocess
import time
from pathlib import Path
from time import time_ns

import yaml

from daqhats import AnalogInputRange

from calibrate import apply_calibration
from mcc_reader import DEFAULT_TIMEOUT_MARGIN_S, open_mcc128, read_block, start_scan
from metrics import AcquisitionMetrics
from sender import InfluxSender, to_line


logger = logging.getLogger(__name__)


class _CommitFilter(logging.Filter):
    """Attach the repository commit hash to every log record."""

    def __init__(self, commit_hash: str) -> None:
        super().__init__()
        self._commit_hash = commit_hash

    def filter(self, record: logging.LogRecord) -> bool:  # pragma: no cover - trivial
        record.commit = self._commit_hash
        return True


def _discover_repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _collect_commit_hash() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=_discover_repo_root(),
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:  # pragma: no cover - fall back to unknown when git not available
        return "unknown"


def configure_logging() -> None:
    """Configure application logging with the commit hash in every record."""

    level_name = os.getenv("DAQ_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    commit_hash = _collect_commit_hash()
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)s [commit:%(commit)s] %(name)s: %(message)s",
        )
    else:
        root_logger.setLevel(level)

    root_logger.addFilter(_CommitFilter(commit_hash))
    logger.debug("Logging configured", extra={"commit": commit_hash})


def _resolve_metrics_interval(cfg: dict) -> float:
    env_value = os.getenv("DAQ_METRICS_LOG_INTERVAL_S")
    if env_value:
        try:
            return float(env_value)
        except ValueError:
            logger.warning(
                "Valor inválido para DAQ_METRICS_LOG_INTERVAL_S=%s; usando configuración o valor por defecto.",
                env_value,
            )

    return float(cfg.get("metrics_log_interval_s", 30.0))

def main():
    configure_logging()

    with open("config/sensors.yaml", "r", encoding="utf-8") as fp:
        cfg = yaml.safe_load(fp)
    pi = cfg["station_id"]
    fs = cfg["sample_rate_hz"]
    chans = [c["ch"] for c in cfg["channels"]]
    board = None
    sender = None
    metrics = AcquisitionMetrics(
        log_interval_s=_resolve_metrics_interval(cfg),
        logger=logging.getLogger("edge.scr.metrics"),
    )
    try:
        board = open_mcc128()
        ch_mask, block = start_scan(board, chans, fs, AnalogInputRange.BIP_10V, cfg.get("scan_block_size", 1000))
        sender = InfluxSender(metrics=metrics)
        map_cal = {c["ch"]:(c["sensor"], c["unit"], c["calib"]["gain"], c["calib"]["offset"]) for c in cfg["channels"]}

        ts_step = int(1e9 / fs)

        while True:
            try:
                raw = read_block(board, ch_mask, block, chans, sample_rate_hz=fs)
            except RuntimeError as exc:
                logger.warning("Fallo al leer bloque de adquisición: %s", exc)
                metrics.increment_hardware_overrun()
                metrics.maybe_log()
                time.sleep(DEFAULT_TIMEOUT_MARGIN_S)
                continue
            now_ns = time_ns()
            block_len = len(raw[chans[0]]) if chans else 0
            if block_len == 0:
                continue
            metrics.record_block(block_len, len(chans))
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
        metrics.maybe_log(force=True)

if __name__ == "__main__":
    main()
