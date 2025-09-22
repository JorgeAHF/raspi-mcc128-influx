"""Acquisition session management endpoints."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from threading import Event, Lock, Thread
from typing import Callable, Dict, Literal

import anyio
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from edge.config import (
    StationConfig,
    StorageSettings,
    load_station_config,
    load_storage_settings,
)
from edge.scr.acquisition import AcquisitionRunner, PreviewMessage

from .auth import require_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/acquisition", tags=["acquisition"])

ModeLiteral = Literal["continuous", "timed"]


class StartSessionRequest(BaseModel):
    """Payload used to start an acquisition session."""

    mode: ModeLiteral = Field(
        "continuous", description="Tipo de sesión: continua o temporizada"
    )
    preview: bool = Field(
        True,
        description="Si es True se ejecuta en modo test para exponer vista previa",
    )


class SessionSummary(BaseModel):
    """Metadata describing a session lifecycle."""

    mode: ModeLiteral
    preview: bool
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    station_id: str
    error: str | None = None


class StopResponse(BaseModel):
    message: str
    session: SessionSummary


class PreviewQueue:
    """Thread-safe bridge between the runner and async consumers."""

    def __init__(self, loop: asyncio.AbstractEventLoop, *, maxsize: int = 4) -> None:
        self._loop = loop
        self._queue: asyncio.Queue[PreviewMessage] = asyncio.Queue(maxsize)
        self._closed = False

    def _enqueue(self, item: PreviewMessage, *, force: bool = False) -> None:
        if self._closed and not force:
            return

        def _put() -> None:
            if self._closed and not force:
                return
            if self._queue.full():
                try:
                    dropped = self._queue.get_nowait()
                    self._queue.task_done()
                    if dropped is not None:
                        logger.warning(
                            "Cola de vista previa llena; se descarta un bloque antiguo."
                        )
                except asyncio.QueueEmpty:  # pragma: no cover - carrera improbable
                    pass
            self._queue.put_nowait(item)

        self._loop.call_soon_threadsafe(_put)

    def put_nowait(self, item: PreviewMessage) -> None:
        self._enqueue(item)

    async def get(self) -> PreviewMessage:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    def qsize(self) -> int:
        return self._queue.qsize()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._enqueue(None, force=True)


@dataclass
class AcquisitionSession:
    """Track a running acquisition session in a background thread."""

    runner: AcquisitionRunner
    station: StationConfig
    storage: StorageSettings
    mode: ModeLiteral
    preview_enabled: bool
    loop: asyncio.AbstractEventLoop

    def __post_init__(self) -> None:
        self.preview_queue: PreviewQueue | None = (
            PreviewQueue(self.loop) if self.preview_enabled else None
        )
        self._thread: Thread | None = None
        self._stop_event = Event()
        self._status = "starting"
        self._error: str | None = None
        self._preview_consumers = 0
        self._preview_lock = Lock()
        self.started_at = datetime.now(timezone.utc)
        self.finished_at: datetime | None = None

    # ------------------------------------------------------------------
    def start(self) -> None:
        queue = self.preview_queue if self.preview_enabled else None
        requested_mode = self.mode
        actual_mode = "test" if self.preview_enabled else requested_mode

        def _runner() -> None:
            nonlocal actual_mode
            logger.info(
                "Iniciando sesión de adquisición (mode=%s preview=%s)",
                requested_mode,
                self.preview_enabled,
            )
            self._status = "running"
            try:
                self.runner.run(mode=actual_mode, test_channel=queue)
                if self._status == "running":
                    self._status = "finished"
            except Exception as exc:  # pragma: no cover - requiere hardware real
                self._status = "failed"
                self._error = str(exc)
                logger.exception("La sesión de adquisición falló")
            finally:
                self.finished_at = datetime.now(timezone.utc)
                if self.preview_queue is not None:
                    self.preview_queue.close()
                self._stop_event.set()
                logger.info("Sesión de adquisición finalizada (status=%s)", self._status)

        self._thread = Thread(target=_runner, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    def stop(self, timeout: float = 10.0) -> None:
        if self.preview_queue is not None:
            self.preview_queue.close()
        try:
            self.runner.request_stop()
        except Exception:  # pragma: no cover - defensivo
            logger.exception("Error solicitando stop al runner")
        if not self._stop_event.wait(timeout):
            logger.warning("Timeout esperando cierre de la sesión de adquisición")
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
        if self.finished_at is None:
            self.finished_at = datetime.now(timezone.utc)
        if self._status == "running":
            self._status = "stopped"

    # ------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        if self._stop_event.is_set():
            return False
        thread = self._thread
        if thread and not thread.is_alive():
            self._stop_event.set()
            return False
        return True

    def info(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "preview": self.preview_enabled,
            "status": self._status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "station_id": self.station.station_id,
            "error": self._error,
        }

    def acquire_preview_queue(self) -> PreviewQueue:
        if not self.preview_enabled or self.preview_queue is None:
            raise RuntimeError("La sesión actual no expone vista previa")
        with self._preview_lock:
            if self._preview_consumers >= 1:
                raise RuntimeError("Ya existe un cliente consumiendo la vista previa")
            self._preview_consumers += 1
        return self.preview_queue

    def release_preview_queue(self) -> None:
        with self._preview_lock:
            if self._preview_consumers > 0:
                self._preview_consumers -= 1


RunnerFactory = Callable[[StationConfig, StorageSettings], AcquisitionRunner]


class AcquisitionSessionManager:
    """Coordinate session lifecycle and prevent concurrent runs."""

    def __init__(self, *, runner_factory: RunnerFactory | None = None) -> None:
        self._runner_factory = runner_factory or (
            lambda station, storage: AcquisitionRunner(station=station, storage=storage)
        )
        self._lock = asyncio.Lock()
        self._session: AcquisitionSession | None = None
        self._last_summary: Dict[str, object] | None = None

    async def _cleanup_finished_session_locked(self) -> None:
        session = self._session
        if session and not session.is_active:
            self._last_summary = session.info()
            self._session = None

    async def start_session(self, request: StartSessionRequest) -> Dict[str, object]:
        async with self._lock:
            await self._cleanup_finished_session_locked()
            if self._session is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Ya existe una sesión en ejecución",
                )
            station = await anyio.to_thread.run_sync(load_station_config)
            storage = await anyio.to_thread.run_sync(load_storage_settings)
            runner = self._runner_factory(station, storage)
            loop = asyncio.get_running_loop()
            session = AcquisitionSession(
                runner=runner,
                station=station,
                storage=storage,
                mode=request.mode,
                preview_enabled=request.preview,
                loop=loop,
            )
            session.start()
            self._session = session
            self._last_summary = None
            return session.info()

    async def stop_session(self) -> Dict[str, object]:
        async with self._lock:
            await self._cleanup_finished_session_locked()
            session = self._session
            if session is None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No hay sesiones activas",
                )
            await anyio.to_thread.run_sync(session.stop)
            summary = session.info()
            self._last_summary = summary
            self._session = None
            return summary

    async def current_session(self) -> Dict[str, object] | None:
        async with self._lock:
            await self._cleanup_finished_session_locked()
            session = self._session
            if session is None:
                return None
            return session.info()

    async def last_session(self) -> Dict[str, object] | None:
        async with self._lock:
            await self._cleanup_finished_session_locked()
            if self._session is not None:
                return None
            return self._last_summary

    async def acquire_preview(self) -> tuple[AcquisitionSession, PreviewQueue]:
        async with self._lock:
            await self._cleanup_finished_session_locked()
            session = self._session
            if session is None or not session.preview_enabled:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="No hay sesión con vista previa disponible",
                )
            queue = session.acquire_preview_queue()
            return session, queue

    async def release_preview(self, session: AcquisitionSession) -> None:
        async with self._lock:
            current = self._session
            if current is session:
                session.release_preview_queue()
            else:
                # La sesión finalizó pero se libera el contador igualmente.
                session.release_preview_queue()


session_manager = AcquisitionSessionManager()


@router.post("/start", response_model=SessionSummary, status_code=status.HTTP_202_ACCEPTED)
async def start_acquisition(
    request: StartSessionRequest,
    _: None = Depends(require_token),
) -> Dict[str, object]:
    """Start a new acquisition session."""

    info = await session_manager.start_session(request)
    return info


@router.post("/stop", response_model=StopResponse)
async def stop_acquisition(_: None = Depends(require_token)) -> Dict[str, object]:
    """Stop the active session if present."""

    summary = await session_manager.stop_session()
    return {"message": "Sesión detenida", "session": summary}


@router.get("/session", response_model=Dict[str, object])
async def session_status(_: None = Depends(require_token)) -> Dict[str, object]:
    """Return the active session metadata or the last finished session."""

    current = await session_manager.current_session()
    if current is not None:
        return {"active": True, "session": current}
    last = await session_manager.last_session()
    return {"active": False, "last_session": last}

