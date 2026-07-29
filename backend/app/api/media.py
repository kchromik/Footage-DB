"""Ausliefern von Vorschaubildern, Proxies und Originaldateien.

Videos brauchen Range-Requests, sonst kann der Browser nicht springen und
manche Player laden gar nicht erst los.
"""

from __future__ import annotations

import logging
import mimetypes
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from .. import paths
from ..config import settings
from ..db import get_conn
from ..util import safe_name
from .deps import require_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/media", tags=["media"], dependencies=[Depends(require_user)])

CHUNK = 1024 * 512
RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")
IMAGE_CACHE = "private, max-age=31536000, immutable"


def _iter_file(path: Path, start: int, end: int):
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            data = handle.read(min(CHUNK, remaining))
            if not data:
                break
            remaining -= len(data)
            yield data


def serve_file(
    request: Request,
    path: Path,
    media_type: str | None = None,
    download_name: str | None = None,
    cache: str = "private, max-age=3600",
) -> Response:
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    stat = path.stat()
    size = stat.st_size
    media_type = media_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    headers = {
        "accept-ranges": "bytes",
        "cache-control": cache,
        "last-modified": _http_date(stat.st_mtime),
    }
    if download_name:
        headers["content-disposition"] = (
            f'attachment; filename="{safe_name(download_name)}"'
        )

    range_header = request.headers.get("range")
    start, end = 0, size - 1
    status_code = 200

    if range_header:
        match = RANGE_RE.match(range_header.strip())
        if match:
            raw_start, raw_end = match.groups()
            if raw_start:
                start = int(raw_start)
                end = int(raw_end) if raw_end else size - 1
            elif raw_end:  # letzte N Bytes
                start = max(0, size - int(raw_end))
            if start >= size:
                return Response(
                    status_code=416, headers={"content-range": f"bytes */{size}"}
                )
            end = min(end, size - 1)
            status_code = 206
            headers["content-range"] = f"bytes {start}-{end}/{size}"

    headers["content-length"] = str(end - start + 1)

    if request.method == "HEAD":
        return Response(status_code=status_code, headers=headers, media_type=media_type)

    return StreamingResponse(
        _iter_file(path, start, end),
        status_code=status_code,
        headers=headers,
        media_type=media_type,
    )


def _http_date(timestamp: float) -> str:
    from email.utils import formatdate

    return formatdate(timestamp, usegmt=True)


def _clip_or_404(clip_id: int):
    row = get_conn().execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Clip nicht gefunden")
    return row


@router.api_route("/{clip_id}/poster", methods=["GET", "HEAD"])
def poster(clip_id: int, request: Request) -> Response:
    return serve_file(
        request, paths.poster_path(clip_id), "image/webp", cache=IMAGE_CACHE
    )


@router.api_route("/{clip_id}/sprite", methods=["GET", "HEAD"])
def sprite(clip_id: int, request: Request) -> Response:
    return serve_file(
        request, paths.sprite_path(clip_id), "image/webp", cache=IMAGE_CACHE
    )


@router.api_route("/{clip_id}/play", methods=["GET", "HEAD"])
def play(clip_id: int, request: Request) -> Response:
    clip = _clip_or_404(clip_id)
    if clip["proxy_status"] == "ready":
        return serve_file(request, paths.proxy_path(clip_id), "video/mp4")
    if clip["proxy_status"] == "skipped":
        source = settings.media_root / clip["path"]
        return serve_file(request, source, "video/mp4")
    raise HTTPException(
        status_code=409,
        detail="Vorschau wird noch erzeugt" if clip["proxy_status"] == "pending"
        else "Fuer diesen Clip konnte keine Vorschau erzeugt werden",
    )


@router.api_route("/{clip_id}/download", methods=["GET", "HEAD"])
def download(clip_id: int, request: Request) -> Response:
    clip = _clip_or_404(clip_id)
    source = settings.media_root / clip["path"]
    if not source.exists():
        raise HTTPException(status_code=404, detail="Originaldatei nicht gefunden")
    return serve_file(
        request,
        source,
        download_name=clip["filename"],
        cache="private, max-age=0",
    )


MAX_ZIP_CLIPS = 200


@router.get("/zip")
def download_zip(ids: str = Query(..., description="Kommagetrennte Clip-IDs")) -> Response:
    from zipstream import ZipStream

    try:
        clip_ids = [int(part) for part in ids.split(",") if part.strip()][:MAX_ZIP_CLIPS]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Ungueltige ID-Liste") from exc
    if not clip_ids:
        raise HTTPException(status_code=400, detail="Keine Clips ausgewaehlt")

    placeholders = ",".join("?" * len(clip_ids))
    rows = get_conn().execute(
        f"SELECT id, path, filename FROM clips WHERE id IN ({placeholders})", clip_ids
    ).fetchall()

    stream = ZipStream(sized=True)
    used: set[str] = set()
    added = 0
    for row in rows:
        source = settings.media_root / row["path"]
        if not source.exists():
            continue
        name = safe_name(row["filename"])
        if name in used:
            name = f"{row['id']}_{name}"
        used.add(name)
        stream.add_path(source, name)
        added += 1

    if added == 0:
        raise HTTPException(status_code=404, detail="Keine der Dateien ist verfuegbar")

    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "content-disposition": 'attachment; filename="footage.zip"',
            "content-length": str(len(stream)),
        },
    )
