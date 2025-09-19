import json
import logging
import sys
from pathlib import Path

import pytest


sys.path.append(str(Path(__file__).resolve().parents[1] / "edge" / "scr"))

from metrics import AcquisitionMetrics  # type: ignore  # noqa: E402


def test_acquisition_metrics_logs_block(caplog: pytest.LogCaptureFixture) -> None:
    """Registrar un bloque debe generar métricas con los contadores esperados."""

    logger_name = "test.metrics"
    metrics = AcquisitionMetrics(log_interval_s=60.0, logger=logging.getLogger(logger_name))

    with caplog.at_level(logging.INFO, logger=logger_name):
        metrics.record_block(block_len=2, channel_count=3)
        metrics.increment_samples_sent(6)
        metrics.increment_http_retry(6)
        metrics.report_queue_overrun(dropped=1)
        metrics.maybe_log(force=True)

    metric_records = [rec for rec in caplog.records if rec.message.startswith("acquisition_metrics ")]
    assert metric_records, "Se esperaba al menos un log de métricas acumuladas"

    payload = json.loads(metric_records[-1].message.split(" ", 1)[1])
    counters = payload["counters"]
    delta = payload["delta"]

    assert payload["type"] == "acquisition_metrics"
    assert counters["blocks_processed"] == 1
    assert counters["samples_read"] == 6
    assert counters["samples_enqueued"] == 6
    assert counters["samples_sent"] == 6
    assert counters["http_retries"] == 1
    assert counters["http_retry_lines"] == 6
    assert counters["queue_overruns"] == 1
    assert counters["dropped_samples"] == 1
    assert counters["hardware_overruns"] == 0

    assert delta == counters
