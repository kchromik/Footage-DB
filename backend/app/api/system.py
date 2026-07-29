"""Systemzustand, Statistiken, Scan-Steuerung und Live-Ereignisse."""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from .. import jobs, library, scanner
from ..config import settings
from ..db import get_conn, get_setting, query, query_one
from ..events import bus
from ..media.ffmpeg import describe_acceleration
from ..search import semantic
from ..util import format_duration, human_size
from .deps import require_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])
# Wird unten in router eingehaengt und erbt dadurch den Praefix /api
secured = APIRouter(dependencies=[Depends(require_user)])


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@secured.get("/stats")
def stats() -> dict:
    totals = query_one(
        "SELECT COUNT(*) AS clips, COALESCE(SUM(size_bytes),0) AS bytes, "
        "COALESCE(SUM(duration),0) AS seconds FROM clips WHERE status != 'missing'"
    )
    by_camera = query(
        "SELECT COALESCE(camera_label,'Unbekannt') AS name, COUNT(*) AS count, "
        "COALESCE(SUM(duration),0) AS seconds FROM clips WHERE status != 'missing' "
        "GROUP BY name ORDER BY count DESC LIMIT 30"
    )
    by_year = query(
        "SELECT substr(COALESCE(recorded_at, created_at),1,4) AS year, COUNT(*) AS count "
        "FROM clips WHERE status != 'missing' GROUP BY year ORDER BY year DESC LIMIT 20"
    )
    by_look = query(
        "SELECT COALESCE(look_manual, look, 'unknown') AS name, COUNT(*) AS count "
        "FROM clips WHERE status != 'missing' GROUP BY name ORDER BY count DESC"
    )
    by_resolution = query(
        "SELECT t.name AS name, COUNT(*) AS count FROM clip_tags ct "
        "JOIN tags t ON t.id = ct.tag_id JOIN clips c ON c.id = ct.clip_id "
        "WHERE t.category = 'tech' AND c.status != 'missing' "
        "GROUP BY t.id ORDER BY count DESC LIMIT 20"
    )
    pending = query_one(
        "SELECT "
        "SUM(CASE WHEN poster_status='pending' THEN 1 ELSE 0 END) AS poster, "
        "SUM(CASE WHEN proxy_status='pending' THEN 1 ELSE 0 END) AS proxy, "
        "SUM(CASE WHEN embed_status='pending' THEN 1 ELSE 0 END) AS embed "
        "FROM clips WHERE status = 'indexed'"
    )
    missing = query_one("SELECT COUNT(*) AS n FROM clips WHERE status='missing'")
    errors = query_one("SELECT COUNT(*) AS n FROM clips WHERE status='error'")

    seconds = totals["seconds"] or 0
    return {
        "clips": totals["clips"],
        "bytes": totals["bytes"],
        "size_label": human_size(totals["bytes"] or 0),
        "seconds": seconds,
        "duration_label": format_duration(seconds),
        "missing": missing["n"],
        "errors": errors["n"],
        "pending": {
            "poster": pending["poster"] or 0,
            "proxy": pending["proxy"] or 0,
            "embed": pending["embed"] or 0,
        },
        "by_camera": [dict(row) for row in by_camera],
        "by_year": [dict(row) for row in by_year],
        "by_look": [dict(row) for row in by_look],
        "by_resolution": [dict(row) for row in by_resolution],
        "queue": jobs.queue_stats(),
        "scanning": scanner.is_scanning(),
        "last_scan_at": get_setting("last_scan_at"),
        "semantic": semantic.status(),
        "acceleration": describe_acceleration(),
        "media_root": str(settings.media_root),
    }


@secured.post("/scan")
def trigger_scan() -> dict:
    if scanner.is_scanning():
        return {"started": False, "detail": "Es laeuft bereits ein Scan"}
    scanner.scan_async()
    return {"started": True}


@secured.get("/jobs")
def job_overview(limit: int = 50) -> dict:
    rows = query(
        "SELECT j.id, j.type, j.clip_id, j.state, j.attempts, j.error, j.created_at, "
        "c.filename AS filename FROM jobs j LEFT JOIN clips c ON c.id = j.clip_id "
        "WHERE j.state IN ('running','failed') ORDER BY j.state, j.id DESC LIMIT ?",
        (limit,),
    )
    return {"queue": jobs.queue_stats(), "items": [dict(row) for row in rows]}


@secured.post("/jobs/retry")
def retry_jobs() -> dict:
    count = jobs.retry_failed()
    return {"requeued": count}


@secured.post("/maintenance/cleanup")
def cleanup() -> dict:
    removed_files = library.cleanup_orphan_artifacts()
    removed_tags = library.cleanup_orphan_tags(get_conn())
    return {"removed_artifacts": removed_files, "removed_tags": removed_tags}


@secured.post("/maintenance/purge-missing")
def purge_missing() -> dict:
    rows = query("SELECT id FROM clips WHERE status='missing'")
    for row in rows:
        library.delete_clip(row["id"], remove_file=False)
        semantic.index.remove(row["id"])
    return {"removed": len(rows)}


@secured.get("/events")
async def events(request: Request) -> StreamingResponse:
    """Live-Ereignisse fuer Fortschrittsanzeige und Nachladen von Kacheln."""
    queue = bus.subscribe()

    async def generator():
        try:
            yield b": verbunden\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield b": ping\n\n"
                    continue
                data = json.dumps(payload, ensure_ascii=False)
                yield f"data: {data}\n\n".encode("utf-8")
        finally:
            bus.unsubscribe(queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "cache-control": "no-cache",
            "connection": "keep-alive",
            "x-accel-buffering": "no",
        },
    )


router.include_router(secured)
