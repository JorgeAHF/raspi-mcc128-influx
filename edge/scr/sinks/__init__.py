"""Registro de sinks disponibles y utilidades de construcción."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import List

from edge.config.schema import StorageSettings

from .base import Sample, SampleSink
from .csv import CSVSink
from .ftp import FTPSink
from .influx import InfluxSender

logger = logging.getLogger(__name__)

__all__ = [
    "Sample",
    "SampleSink",
    "CSVSink",
    "FTPSink",
    "InfluxSender",
    "build_sinks",
]


def build_sinks(settings: StorageSettings) -> List[SampleSink]:
    """Inicializa los sinks indicados en la configuración."""

    normalized = [name.lower() for name in settings.sinks] or [settings.driver.lower()]
    sinks: List[SampleSink] = []
    seen = set()

    for name in normalized:
        if name in seen:
            continue
        seen.add(name)
        if name in {"influx", "influxdb", "influxdb_v2"}:
            sinks.append(InfluxSender(settings))
        elif name == "csv":
            if settings.csv.enabled:
                sinks.append(CSVSink(settings.csv))
            else:
                logger.info("CSVSink solicitado pero deshabilitado en la configuración; se omite.")
        elif name in {"ftp", "sftp"}:
            if settings.ftp.enabled:
                ftp_settings = settings.ftp
                if name == "sftp" and ftp_settings.protocol != "sftp":
                    ftp_settings = replace(ftp_settings, protocol="sftp")
                if not ftp_settings.host:
                    logger.error("FTPSink habilitado pero sin host configurado; se omite.")
                    continue
                sinks.append(FTPSink(ftp_settings, settings.csv))
            else:
                logger.info("FTPSink solicitado pero deshabilitado en la configuración; se omite.")
        else:
            logger.warning("Sink '%s' no está soportado y será ignorado.", name)

    return sinks
