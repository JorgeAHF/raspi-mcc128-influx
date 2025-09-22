"""Sink que sube archivos CSV generados localmente a un servidor FTP/SFTP."""

from __future__ import annotations

import ftplib
import logging
import posixpath
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from time import monotonic
from typing import Sequence

try:  # pragma: no cover - dependencia opcional
    import paramiko
except Exception:  # pragma: no cover - evitar fallo si no está disponible
    paramiko = None  # type: ignore[assignment]

from edge.config.schema import CSVSinkSettings, FTPSinkSettings

from .base import Sample, SampleSink
from .csv import CSVSink

logger = logging.getLogger(__name__)


class FTPSink(SampleSink):
    """Publica periódicamente los CSV en un servidor remoto."""

    def __init__(self, settings: FTPSinkSettings, csv_settings: CSVSinkSettings) -> None:
        self.settings = settings
        target_dir = settings.local_dir or csv_settings.directory
        csv_cfg = replace(csv_settings, enabled=True, directory=target_dir, rotation=csv_settings.rotation)
        self._csv_sink = CSVSink(csv_cfg)
        self._last_upload = monotonic()

    def open(self) -> None:
        if not self.settings.host:
            logger.error("FTPSink sin host configurado; se ignora.")
            return
        self._csv_sink.open()
        Path(self._csv_sink.settings.directory).mkdir(parents=True, exist_ok=True)

    def handle_sample(self, sample: Sample) -> None:
        if not self.settings.host:
            return
        self._csv_sink.handle_sample(sample)
        if self.settings.rotation == "periodic":
            interval = self.settings.upload_interval_s
            if interval is None:
                logger.debug("FTPSink en modo periódico sin intervalo configurado; omitiendo subida.")
                return
            now = monotonic()
            if now - self._last_upload >= interval:
                self._upload_pending_files()
                self._last_upload = now

    def close(self) -> None:
        if not self.settings.host:
            return
        self._csv_sink.close()
        self._upload_pending_files()

    # Métodos auxiliares ------------------------------------------------------
    def _upload_pending_files(self) -> None:
        files = list(self._csv_sink.list_files())
        if not files:
            return
        self._csv_sink.flush()
        protocol = self.settings.protocol.lower()
        try:
            if protocol == "sftp":
                self._upload_via_sftp(files)
            else:
                self._upload_via_ftp(files)
        except Exception:  # pragma: no cover - registro del fallo
            logger.exception("Error subiendo archivos via %s", protocol)

    def _upload_via_ftp(self, files: Sequence[Path]) -> None:
        port = self.settings.port or 21
        with closing(ftplib.FTP()) as ftp:
            ftp.connect(self.settings.host, port)
            ftp.login(self.settings.username or "", self.settings.password or "")
            ftp.set_pasv(self.settings.passive)
            self._ensure_remote_dir_ftp(ftp, self.settings.remote_dir)
            for path in files:
                with path.open("rb") as fh:
                    logger.info("Subiendo %s via FTP", path.name)
                    ftp.storbinary(f"STOR {path.name}", fh)

    def _upload_via_sftp(self, files: Sequence[Path]) -> None:
        if paramiko is None:
            logger.error("paramiko es obligatorio para conexiones SFTP")
            return
        port = self.settings.port or 22
        transport = paramiko.Transport((self.settings.host, port))
        transport.connect(username=self.settings.username, password=self.settings.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            self._ensure_remote_dir_sftp(sftp, self.settings.remote_dir)
            for path in files:
                remote_path = self._join_remote(self.settings.remote_dir, path.name)
                logger.info("Subiendo %s via SFTP", path.name)
                sftp.put(str(path), remote_path)
        finally:
            sftp.close()
            transport.close()

    @staticmethod
    def _ensure_remote_dir_ftp(ftp: ftplib.FTP, remote_dir: str) -> None:
        parts = [segment for segment in remote_dir.split("/") if segment]
        if remote_dir.startswith("/"):
            ftp.cwd("/")
        for segment in parts:
            try:
                ftp.cwd(segment)
            except ftplib.error_perm:
                ftp.mkd(segment)
                ftp.cwd(segment)

    @staticmethod
    def _ensure_remote_dir_sftp(sftp_client, remote_dir: str) -> None:
        parts = [segment for segment in remote_dir.split("/") if segment]
        current = "/" if remote_dir.startswith("/") else "."
        for segment in parts:
            current = posixpath.join(current, segment)
            try:
                sftp_client.chdir(current)
            except IOError:
                sftp_client.mkdir(current)
                sftp_client.chdir(current)

    @staticmethod
    def _join_remote(base: str, name: str) -> str:
        if base.endswith("/"):
            return f"{base}{name}"
        return f"{base}/{name}"
