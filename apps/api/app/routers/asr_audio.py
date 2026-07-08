"""Short-lived signed audio proxy for external ASR downloaders."""

from __future__ import annotations

import mimetypes
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from voiceqa_shared import asr_audio_proxy, gcs

from app.ratelimit import limiter
from app.settings import settings

router = APIRouter(prefix="/api/asr-audio", tags=["asr-audio"])

CHUNK_SIZE = 1024 * 1024


def _iter_gcs(uri: str, size: int) -> Iterator[bytes]:
    start = 0
    while start < size:
        end = min(size - 1, start + CHUNK_SIZE - 1)
        yield gcs.read_uri_range(uri, start, end)
        start = end + 1


@router.get("")
@limiter.exempt
async def get_asr_audio(token: str = Query(min_length=1)) -> StreamingResponse:
    try:
        uri = asr_audio_proxy.parse_token(token, settings.INTERNAL_API_SECRET.get_secret_value())
        size = gcs.object_size(uri)
    except ValueError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "audio not found") from exc

    _, key = gcs.from_uri(uri)
    filename = Path(key).name
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return StreamingResponse(
        _iter_gcs(uri, size),
        media_type=media_type,
        headers={
            "Content-Length": str(size),
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
