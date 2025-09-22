"""High-level acquisition runner orchestrating MCC128 scans."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from time import time_ns
from typing import Callable, Dict, List, Optional, Protocol, Sequence, runtime_checkable

from edge.config.schema import StationConfig, StorageSettings

from .calibrate import apply_calibration
from .mcc_reader import open_mcc128, read_block, start_scan
from .sinks import Sample, SampleSink, build_sinks

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AcquisitionBlock:
    """Bundle of raw samples captured in a single MCC128 read."""

    timestamps_ns: List[int]
    values_by_channel: Dict[int, List[float]]
    captured_at_ns: int


@dataclass(frozen=True)
class CalibratedChannelBlock:
    """Calibrated samples for a single channel inside a block."""

    index: int
    name: str
    unit: str
    values: List[float]


@dataclass(frozen=True)
class CalibratedBlock:
    """Calibrated representation of a block ready for preview broadcasting."""

    station_id: str
    timestamps_ns: List[int]
    channels: Dict[int, CalibratedChannelBlock]
    captured_at_ns: int


PreviewMessage = Optional[CalibratedBlock]


@runtime_checkable
class _SupportsPutNowait(Protocol):
    def put_nowait(self, item: PreviewMessage) -> None:  # pragma: no cover - Protocol signature
        """Queue-like interface supporting put_nowait."""


@runtime_checkable
class _SupportsPublish(Protocol):
    def publish(self, item: PreviewMessage) -> None:  # pragma: no cover - Protocol signature
        """Pub/sub style interface."""


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
        self._broadcast_channel: Optional[_SupportsPutNowait | _SupportsPublish] = None
        self._test_mode_active = False
        self._test_blocks_broadcast = 0
        self._test_samples_broadcast = 0

    def request_stop(self) -> None:
        """Signal the runner to stop after completing the current iteration."""

        self._stop_requested = True

    def run(
        self,
        mode: str = "continuous",
        *,
        test_channel: Optional[_SupportsPutNowait | _SupportsPublish] = None,
    ) -> None:
        """Start the acquisition loop until completion or stop request."""

        if mode not in {"continuous", "timed", "test"}:
            raise ValueError(f"Unsupported acquisition mode: {mode}")

        self._broadcast_channel = test_channel if mode == "test" else None
        self._test_mode_active = mode == "test"
        self._test_blocks_broadcast = 0
        self._test_samples_broadcast = 0
        if self._test_mode_active and self._broadcast_channel is None:
            logger.warning(
                "Modo test activado sin canal de publicación; no se emitirá vista previa."
            )

        board = None
        ch_mask = 0
        if self._test_mode_active:
            self._active_sinks = ()
            logger.info(
                "Modo test habilitado: se omite la inicialización de sinks de almacenamiento."
            )
        else:
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
            timed_mode = mode in {"timed", "test"}
            if timed_mode and self.settings.duration_s is not None:
                acquisition_deadline_ns = next_ts_ns + int(self.settings.duration_s * 1e9)

            remaining_samples: Optional[int] = None
            if timed_mode and self.settings.total_samples is not None:
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
            if self._test_mode_active:
                self._publish_preview_block(None)
                if self._test_blocks_broadcast or self._test_samples_broadcast:
                    logger.info(
                        "Modo test finalizado: %d bloques y %d muestras emitidas para vista previa.",
                        self._test_blocks_broadcast,
                        self._test_samples_broadcast,
                    )
            self._broadcast_channel = None
            self._test_mode_active = False

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
        should_broadcast = self._test_mode_active and self._broadcast_channel is not None
        if not self._active_sinks and not should_broadcast:
            return
        station_id = self.station.station_id
        calibrated_channels: Dict[int, CalibratedChannelBlock] = {}
        for channel in self.channels:
            values = block.values_by_channel.get(channel.index, [])
            calibrated = apply_calibration(values, channel.calibration.gain, channel.calibration.offset)
            if calibrated:
                calibrated_channels[channel.index] = CalibratedChannelBlock(
                    index=channel.index,
                    name=channel.name,
                    unit=channel.unit,
                    values=[float(value) for value in calibrated],
                )
            if self._active_sinks:
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

        if should_broadcast and calibrated_channels:
            preview_block = CalibratedBlock(
                station_id=station_id,
                timestamps_ns=list(block.timestamps_ns),
                channels=calibrated_channels,
                captured_at_ns=block.captured_at_ns,
            )
            self._publish_preview_block(preview_block)

    def _dispatch_sample(self, sample: Sample) -> None:
        for sink in self._active_sinks:
            try:
                sink.handle_sample(sample)
            except Exception:  # pragma: no cover - registro de errores
                logger.exception("Sink %r rechazó la muestra", sink)

    def _publish_preview_block(self, block: PreviewMessage) -> None:
        channel = self._broadcast_channel
        if channel is None:
            return
        try:
            if isinstance(channel, _SupportsPutNowait):
                channel.put_nowait(block)
            elif isinstance(channel, _SupportsPublish):
                channel.publish(block)
            else:
                raise TypeError(
                    f"El canal de broadcast no implementa put_nowait/publish: {type(channel)!r}"
                )
        except Exception:
            logger.exception("Error al publicar bloque de vista previa")
            return

        if block is None:
            logger.debug("Señal de finalización enviada al canal de vista previa.")
            return

        self._test_blocks_broadcast += 1
        samples = sum(len(ch.values) for ch in block.channels.values())
        self._test_samples_broadcast += samples
        queue_size = "n/a"
        qsize = getattr(channel, "qsize", None)
        if callable(qsize):
            try:
                queue_size = qsize()
            except Exception:  # pragma: no cover - métricas best effort
                queue_size = "n/a"
        logger.debug(
            "Bloque de vista previa #%d emitido con %d muestras (qsize=%s)",
            self._test_blocks_broadcast,
            samples,
            queue_size,
        )
