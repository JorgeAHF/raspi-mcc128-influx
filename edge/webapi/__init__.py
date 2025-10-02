"""FastAPI application exposing configuration and acquisition endpoints."""

from __future__ import annotations

from fastapi import FastAPI

from .acquisition import router as acquisition_router
from .configuration import router as config_router
from .logs import router as logs_router
from .preview import router as preview_router
from .system import router as system_router

app = FastAPI(title="MCC128 Edge Web API", version="1.0.0")

app.include_router(config_router)
app.include_router(acquisition_router)
app.include_router(preview_router)
app.include_router(system_router)
app.include_router(logs_router)


__all__ = ["app"]

