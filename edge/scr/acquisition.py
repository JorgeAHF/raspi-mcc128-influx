"""High-level acquisition runner orchestrating MCC128 scans."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import time_ns
from typing import Callable, Dict, List, Optional, Sequence

from edge.config.schema import StationConfig, StorageSettings

from calibrate import apply_calibration
from mcc_reader import open_mcc128, read_block, start_scan
from sinks import Sample, SampleSink, build_sinks

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcquisitionBlock:
    """Bundle of raw samples captured in a single MCC128 read."""

    timestamps_ns: List[int]
    values_by_channel: Dict[int, List[float]]
    captured_at_ns: int


def _consume_block_timestamps(next_ts_ns: int, block_len: int, ts_step: int) -> tuple[List[int], int]:
    """Return timestamps for a block and the updated accumulator."""

    timestamps = [next_ts_ns + i * ts_step for i in range(block_len)]
    return timestamps, next_ts_ns + block_len * ts_step


class AcquisitionRunner:
    """Coordinate MCC128 scans and deliver samples to the configured sinks."""

    def __init__(
        self,
        station: StationConfig,
        storage: StorageSettings,
        *,
        sink_factory: Callable[[StorageSettings], Sequence[SampleSink]] = build_sinks,
    ) -> None:
        self.station = station
        self.settings = station.acquisition
        self.channels = list(station.channels)
        self.storage = storage
        self._sink_factory = sink_factory
        self._stop_requested = False
        self._active_sinks: Sequence[SampleSink] = ()

    def request_stop(self) -> None:
        """Signal the runner to stop after completing the current iteration."""

        self._stop_requested = True

    def run(self, mode: str = "continuous") -> None:
        """Start the acquisition loop until completion or stop request."""

        if mode not in {"continuous", "timed"}:
            raise ValueError(f"Unsupported acquisition mode: {mode}")

        board = None
        ch_mask = 0
        self._active_sinks = self._initialize_sinks()
        try:
            board = open_mcc128()
            channel_indices = [ch.index for ch in self.channels]
            if not channel_indices:
                logger.warning("No hay canales configurados; se omite la adquisición.")
                return
            channel_ranges = {ch.index: ch.voltage_range for ch in self.channels}
            ch_mask, block_samples = start_scan(
                board,
                channel_indices,
                self.settings.sample_rate_hz,
                channel_ranges=channel_ranges,
                block_samples=self.settings.block_size,
            )

            ts_step = int(1e9 / self.settings.sample_rate_hz)
            next_ts_ns = time_ns()
            drift_raw = self.settings.drift_detection.correction_threshold_ns
            drift_threshold_ns = int(drift_raw) if drift_raw is not None else None

            acquisition_deadline_ns: Optional[int] = None
            if mode == "timed" and self.settings.duration_s is not None:
                acquisition_deadline_ns = next_ts_ns + int(self.settings.duration_s * 1e9)

            remaining_samples: Optional[int] = None
            if mode == "timed" and self.settings.total_samples is not None:
                remaining_samples = int(self.settings.total_samples)

            while True:
                if self._stop_requested:
                    logger.info("Stop requested; ending acquisition loop.")
                    break
                if acquisition_deadline_ns is not None and time_ns() >= acquisition_deadline_ns:
                    logger.info("Acquisition duration exhausted; stopping scan.")
                    break

                raw = read_block(
                    board,
                    ch_mask,
                    block_samples,
                    channel_indices,
                    sample_rate_hz=self.settings.sample_rate_hz,
                )
                block_captured_ns = time_ns()
                block_len = len(raw[channel_indices[0]]) if channel_indices else 0
                if block_len == 0:
                    continue

                if remaining_samples is not None and block_len > remaining_samples:
                    block_len = remaining_samples
                    raw = {ch: vals[:block_len] for ch, vals in raw.items()}

                timestamps, candidate_next_ts_ns = _consume_block_timestamps(
                    next_ts_ns, block_len, ts_step
                )

                block = AcquisitionBlock(
                    timestamps_ns=timestamps,
                    values_by_channel=raw,
                    captured_at_ns=block_captured_ns,
                )
                self._handle_block(block)

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

                if remaining_samples is not None:
                    remaining_samples -= block_len
                    if remaining_samples <= 0:
                        logger.info("Sample budget exhausted; stopping scan.")
                        break
                if (
                    acquisition_deadline_ns is not None
                    and block_captured_ns >= acquisition_deadline_ns
                ):
                    logger.info("Acquisition duration exhausted after delivering block.")
                    break
        finally:
            self._shutdown_sinks()
            if board is not None:
                stop_scan = getattr(board, "a_in_scan_stop", None)
                if callable(stop_scan):
                    stop_scan()
                cleanup_scan = getattr(board, "a_in_scan_cleanup", None)
                if callable(cleanup_scan):
                    cleanup_scan()

    # Internal helpers --------------------------------------------------------
    def _initialize_sinks(self) -> Sequence[SampleSink]:
        sinks = list(self._sink_factory(self.storage))
        if not sinks:
            logger.warning("No hay sinks configurados; las muestras no se almacenarán.")
            return []
        ready: List[SampleSink] = []
        for sink in sinks:
            try:
                sink.open()
            except Exception:  # pragma: no cover - mantenimiento
                logger.exception("Error al inicializar sink %r", sink)
                continue
            ready.append(sink)
        if not ready:
            logger.error("No fue posible inicializar ningún sink.")
        return ready

    def _shutdown_sinks(self) -> None:
        for sink in self._active_sinks:
            try:
                sink.close()
            except Exception:  # pragma: no cover - mantenimiento
                logger.exception("Error al cerrar sink %r", sink)
        self._active_sinks = ()

    def _handle_block(self, block: AcquisitionBlock) -> None:
        if not self._active_sinks:
            return
        station_id = self.station.station_id
        for channel in self.channels:
            values = block.values_by_channel.get(channel.index, [])
            calibrated = apply_calibration(values, channel.calibration.gain, channel.calibration.offset)
            for ts_ns, value in zip(block.timestamps_ns, calibrated):
                tags = {
                    "pi": station_id,
                    "sensor": channel.name,
                    "unidad": channel.unit,
                    "canal": channel.index,
                }
                metadata = {
                    "measurement": "lvdt",
                    "tags": tags,
                    "station_id": station_id,
                    "sensor_name": channel.name,
                    "unit": channel.unit,
                }
                sample = Sample(
                    channel=channel.index,
                    timestamp_ns=ts_ns,
                    calibrated_values={"valor": float(value)},
                    metadata=metadata,
                )
                self._dispatch_sample(sample)

    def _dispatch_sample(self, sample: Sample) -> None:
        for sink in self._active_sinks:
            try:
                sink.handle_sample(sample)
            except Exception:  # pragma: no cover - registro de errores
                logger.exception("Sink %r rechazó la muestra", sink)
