"""Uvicorn bootstrap for the MCC128 Web API."""

from __future__ import annotations

import os

import uvicorn

from . import app

def main() -> None:
    host = os.environ.get("EDGE_WEBAPI_HOST", "0.0.0.0")
    port = int(os.environ.get("EDGE_WEBAPI_PORT", "8000"))
    reload_flag = os.environ.get("EDGE_WEBAPI_RELOAD", "0")
    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=reload_flag.lower() in {"1", "true", "yes"},
        log_level=os.environ.get("EDGE_WEBAPI_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()

