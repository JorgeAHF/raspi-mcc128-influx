"""Preview streaming endpoints."""

from __future__ import annotations

import json
from typing import Iterable, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from edge.scr.preview import PreviewOptions, stream_preview

from .acquisition import session_manager
from .auth import require_token

router = APIRouter(prefix="/preview", tags=["preview"])


def _parse_channels(raw: Optional[Iterable[int]]) -> Optional[List[int]]:
    if raw is None:
        return None
    return [int(ch) for ch in raw]


@router.get("/stream")
async def preview_stream(
    request: Request,
    channels: Optional[List[int]] = Query(None, description="Lista de índices de canal"),
    max_duration_s: Optional[float] = Query(
        None, description="Cortar el stream tras esta cantidad de segundos"
    ),
    downsample: int = Query(1, ge=1, description="Tomar una muestra cada N"),
    _: None = Depends(require_token),
):
    """Yield preview samples using Server-Sent Events."""

    try:
        session, queue = await session_manager.acquire_preview()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc

    options = PreviewOptions(
        channels=_parse_channels(channels),
        max_duration_s=max_duration_s,
        downsample=downsample,
    )

    async def event_source():
        try:
            async for payload in stream_preview(queue, session.station, options=options):
                if await request.is_disconnected():
                    break
                data = json.dumps(payload, ensure_ascii=False)
                yield f"data: {data}\n\n"
        finally:
            await session_manager.release_preview(session)

    headers = {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
    }
    return StreamingResponse(event_source(), media_type="text/event-stream", headers=headers)

