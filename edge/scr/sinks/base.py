"""Interfaces y utilidades comunes para sinks de almacenamiento."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Protocol, runtime_checkable


@dataclass(frozen=True)
class Sample:
    """Representa una muestra calibrada lista para enviar a un sink."""

    channel: int
    timestamp_ns: int
    calibrated_values: Mapping[str, float]
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def with_metadata(self, **extra: Any) -> "Sample":
        """Devuelve una copia con metadatos adicionales."""

        merged: MutableMapping[str, Any] = dict(self.metadata)
        merged.update(extra)
        return Sample(
            channel=self.channel,
            timestamp_ns=self.timestamp_ns,
            calibrated_values=self.calibrated_values,
            metadata=dict(merged),
        )


@runtime_checkable
class SampleSink(Protocol):
    """Contrato mínimo para los sinks de almacenamiento."""

    def open(self) -> None:
        """Inicializa recursos del sink previo a recibir datos."""

    def handle_sample(self, sample: Sample) -> None:
        """Procesa una muestra calibrada."""

    def close(self) -> None:
        """Libera los recursos asociados al sink."""
