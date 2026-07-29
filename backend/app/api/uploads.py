"""Upload grosser Dateien in Haeppchen, mit Wiederaufnahme nach Abbruch.

Der Browser meldet Dateiname und Groesse an, laedt danach Bloecke fester
Groesse hoch und schliesst am Ende ab. Jeder Block landet per pwrite an
seiner Position in einer Datei, dadurch entfaellt das Zusammensetzen.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import jobs, library, organize
from ..config import settings
from ..db import get_conn
from ..events import bus
from ..metadata.probe import probe_file
from ..metadata.rules import derive
from ..util import safe_join, safe_name
from .deps import require_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"], dependencies=[Depends(require_user)])

MAX_SIZE = 500 * 1024 * 1024 * 1024  # 500 GB, faengt nur Unsinn ab


def _part_file(upload_id: str) -> Path:
    return settings.uploads_dir / f"{upload_id}.part"


class InitRequest(BaseModel):
    filename: str
    size: int = Field(gt=0, le=MAX_SIZE)
    subdir: str = ""


@router.post("/init")
def init_upload(payload: InitRequest) -> dict:
    filename = safe_name(payload.filename)
    if Path(filename).suffix.lower() not in settings.extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Dateityp wird nicht unterstuetzt: {Path(filename).suffix}",
        )

    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM uploads WHERE filename = ? AND size_bytes = ? AND state = 'open' "
        "ORDER BY created_at DESC LIMIT 1",
        (filename, payload.size),
    ).fetchone()
    if existing and _part_file(existing["id"]).exists():
        received = _received_chunks(existing["id"])
        return {
            "id": existing["id"],
            "chunk_size": existing["chunk_size"],
            "chunk_count": existing["chunk_count"],
            "received": received,
            "resumed": True,
        }

    chunk_size = settings.upload_chunk_size
    chunk_count = max(1, -(-payload.size // chunk_size))
    upload_id = uuid.uuid4().hex

    settings.uploads_dir.mkdir(parents=True, exist_ok=True)
    _part_file(upload_id).touch()

    conn.execute(
        "INSERT INTO uploads(id, filename, size_bytes, chunk_size, chunk_count, subdir) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (upload_id, filename, payload.size, chunk_size, chunk_count, payload.subdir.strip("/")),
    )
    return {
        "id": upload_id,
        "chunk_size": chunk_size,
        "chunk_count": chunk_count,
        "received": [],
        "resumed": False,
    }


def _received_chunks(upload_id: str) -> list[int]:
    rows = get_conn().execute(
        "SELECT idx FROM upload_chunks WHERE upload_id = ? ORDER BY idx", (upload_id,)
    ).fetchall()
    return [row["idx"] for row in rows]


def _upload_or_404(upload_id: str):
    row = get_conn().execute("SELECT * FROM uploads WHERE id = ?", (upload_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Upload unbekannt")
    return row


@router.get("/{upload_id}")
def upload_status(upload_id: str) -> dict:
    row = _upload_or_404(upload_id)
    return {
        "id": row["id"],
        "filename": row["filename"],
        "size": row["size_bytes"],
        "chunk_size": row["chunk_size"],
        "chunk_count": row["chunk_count"],
        "state": row["state"],
        "received": _received_chunks(upload_id),
    }


@router.put("/{upload_id}/chunk/{index}")
async def upload_chunk(upload_id: str, index: int, request: Request) -> dict:
    row = _upload_or_404(upload_id)
    if row["state"] != "open":
        raise HTTPException(status_code=409, detail="Upload ist bereits abgeschlossen")
    if index < 0 or index >= row["chunk_count"]:
        raise HTTPException(status_code=400, detail="Blocknummer liegt ausserhalb")

    offset = index * row["chunk_size"]
    expected = min(row["chunk_size"], row["size_bytes"] - offset)
    part = _part_file(upload_id)

    handle = os.open(part, os.O_WRONLY | os.O_CREAT)
    written = 0
    try:
        async for piece in request.stream():
            if not piece:
                continue
            if written + len(piece) > expected:
                raise HTTPException(status_code=400, detail="Block ist zu gross")
            os.pwrite(handle, piece, offset + written)
            written += len(piece)
    finally:
        os.close(handle)

    if written != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Block unvollstaendig: {written} statt {expected} Bytes",
        )

    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO upload_chunks(upload_id, idx, size) VALUES (?, ?, ?)",
        (upload_id, index, written),
    )
    conn.execute(
        "UPDATE uploads SET updated_at = datetime('now') WHERE id = ?", (upload_id,)
    )
    done = conn.execute(
        "SELECT COUNT(*) AS n FROM upload_chunks WHERE upload_id = ?", (upload_id,)
    ).fetchone()["n"]
    return {"index": index, "received": done, "total": row["chunk_count"]}


@router.post("/{upload_id}/complete")
def complete_upload(upload_id: str) -> dict:
    row = _upload_or_404(upload_id)
    conn = get_conn()

    if row["state"] == "complete" and row["clip_id"]:
        return {"clip_id": row["clip_id"], "path": row["target_path"], "already": True}

    received = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(SUM(size),0) AS total FROM upload_chunks "
        "WHERE upload_id = ?",
        (upload_id,),
    ).fetchone()
    if received["n"] != row["chunk_count"] or received["total"] != row["size_bytes"]:
        missing = sorted(set(range(row["chunk_count"])) - set(_received_chunks(upload_id)))
        raise HTTPException(
            status_code=409,
            detail=f"Upload unvollstaendig, es fehlen {len(missing)} Bloecke",
        )

    part = _part_file(upload_id)
    if not part.exists() or part.stat().st_size != row["size_bytes"]:
        raise HTTPException(status_code=409, detail="Zwischendatei passt nicht zur Groesse")

    target_rel = _target_path(part, row["filename"], row["subdir"])
    destination = settings.media_root / target_rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    part.replace(destination)

    stat = destination.stat()
    clip_id, _ = library.upsert_scanned_file(target_rel, stat)
    jobs.enqueue("probe", clip_id)

    conn.execute(
        "UPDATE uploads SET state='complete', target_path=?, clip_id=?, "
        "updated_at=datetime('now') WHERE id=?",
        (target_rel, clip_id, upload_id),
    )
    conn.execute("DELETE FROM upload_chunks WHERE upload_id = ?", (upload_id,))
    bus.publish("upload", id=upload_id, clip_id=clip_id, state="complete")
    log.info("Upload abgeschlossen: %s", target_rel)
    return {"clip_id": clip_id, "path": target_rel, "already": False}


def _target_path(temp_file: Path, filename: str, subdir: str) -> str:
    """Bestimmt den Zielpfad, wenn gewuenscht direkt einsortiert."""
    if subdir:
        try:
            safe_join(settings.media_root, subdir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        base = subdir.strip("/")
        return organize.unique_target(base, safe_name(filename), set())

    if not settings.organize_uploads:
        return organize.unique_target("", safe_name(filename), set())

    try:
        # Dieselbe Regelkette wie beim Scan, damit eine hochgeladene Datei
        # im selben Ordner landet wie eine per NAS-Freigabe kopierte.
        probe = probe_file(temp_file)
        derived = derive(probe, filename, filename)
        return organize.target_for_new_file(filename, probe.recorded_at, derived.camera_label)
    except Exception as exc:  # noqa: BLE001
        log.warning("Einsortieren nicht moeglich, Datei landet im Wurzelordner: %s", exc)
        return organize.unique_target("", safe_name(filename), set())


@router.delete("/{upload_id}")
def abort_upload(upload_id: str) -> dict:
    row = _upload_or_404(upload_id)
    _part_file(upload_id).unlink(missing_ok=True)
    conn = get_conn()
    conn.execute("DELETE FROM upload_chunks WHERE upload_id = ?", (upload_id,))
    conn.execute("UPDATE uploads SET state='aborted' WHERE id = ?", (upload_id,))
    return {"ok": True, "filename": row["filename"]}


def cleanup_stale_uploads(max_age_hours: int = 48) -> int:
    """Raeumt liegengebliebene Zwischendateien auf (beim Start aufgerufen)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id FROM uploads WHERE state = 'open' "
        "AND updated_at < datetime('now', ?)",
        (f"-{max_age_hours} hours",),
    ).fetchall()
    for row in rows:
        _part_file(row["id"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM upload_chunks WHERE upload_id = ?", (row["id"],))
        conn.execute("UPDATE uploads SET state='aborted' WHERE id = ?", (row["id"],))
    return len(rows)
