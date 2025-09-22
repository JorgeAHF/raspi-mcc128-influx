"""Compatibilidad hacia atrás para importaciones previas de InfluxSender."""

from sinks.influx import InfluxSender, to_line

__all__ = ["InfluxSender", "to_line"]
