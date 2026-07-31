"""Upload großer Dateien in Häppchen, mit Wiederaufnahme nach Abbruch.

Der Browser meldet Dateiname und Größe an, lädt danach Blöcke fester
Größe hoch und schließt am Ende ab. Jeder Block landet per pwrite an
seiner Position in einer Datei, dadurch entfällt das Zusammensetzen.
"""

from __future__ import annotations

import errno
import functools
import json
import logging
import os
import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .. import jobs, library, organize
from ..config import settings
from ..db import get_conn, reindex_fts
from ..events import bus
from ..metadata.probe import probe_file
from ..metadata.rules import derive
from ..settings_store import runtime
from ..util import safe_join, safe_name
from .deps import require_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"], dependencies=[Depends(require_user)])

MAX_SIZE = 500 * 1024 * 1024 * 1024  # 500 GB, fängt nur Unsinn ab

# Zwischenablage für laufende Uploads, versteckt im Medienordner
STAGING_DIRNAME = ".footagedb-incoming"


@functools.lru_cache(maxsize=1)
def staging_dir() -> Path:
    """Wo die Blöcke während des Uploads landen.

    Am Ende wird die fertige Datei nur umbenannt. Das geht nur innerhalb
    desselben Dateisystems, deshalb liegt die Zwischendatei möglichst schon
    im Medienordner. Auf einem NAS sind /data und /media meist getrennte
    Mounts, und eine 30-GB-Datei erst auf den Cache und dann noch einmal auf
    den Share zu schreiben wäre doppelte Arbeit und doppelter Platzbedarf.

    Lässt sich dort nicht schreiben, fällt es auf das Datenverzeichnis
    zurück. Dann kopiert shutil.move eben über die Dateisystemgrenze.
    """
    candidate = settings.media_root / STAGING_DIRNAME
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".schreibtest"
        probe.write_bytes(b"ok")
        probe.unlink()
        return candidate
    except OSError as exc:
        log.warning(
            "Medienordner nicht beschreibbar (%s), Uploads werden in %s "
            "zwischengelagert und am Ende kopiert",
            exc,
            settings.uploads_dir,
        )
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        return settings.uploads_dir


def media_writable() -> bool:
    """Direkter Schreibtest auf den Medienordner, ohne Zwischenspeicher.

    Wird beim Anmelden eines Uploads geprüft, damit nicht erst 30 GB
    übertragen werden und der letzte Schritt dann scheitert.
    """
    probe = settings.media_root / ".footagedb-schreibtest"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _part_file(upload_id: str) -> Path:
    # Eine bereits begonnene Zwischendatei am alten Ort weiterverwenden,
    # damit angefangene Uploads einen Neustart überleben
    legacy = settings.uploads_dir / f"{upload_id}.part"
    preferred = staging_dir() / f"{upload_id}.part"
    if legacy != preferred and legacy.exists() and not preferred.exists():
        return legacy
    return preferred


class InitRequest(BaseModel):
    filename: str
    size: int = Field(gt=0, le=MAX_SIZE)
    subdir: str = ""
    # Tags, die der Clip nach dem Hochladen bekommen soll
    tags: list[str] = Field(default_factory=list, max_length=40)


@router.post("/init")
def init_upload(payload: InitRequest) -> dict:
    filename = safe_name(payload.filename)
    if Path(filename).suffix.lower() not in settings.extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Dateityp wird nicht unterstützt: {Path(filename).suffix}",
        )

    if not media_writable():
        raise HTTPException(
            status_code=503,
            detail=(
                "In den Medienordner kann nicht geschrieben werden, deshalb sind "
                "Uploads gerade nicht möglich. Die Systemprüfung unter Werkzeuge "
                "zeigt, welche Benutzer-IDs nötig wären."
            ),
        )

    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM uploads WHERE filename = ? AND size_bytes = ? AND state = 'open' "
        "ORDER BY created_at DESC LIMIT 1",
        (filename, payload.size),
    ).fetchone()
    if existing and _part_file(existing["id"]).exists():
        conn.execute(
            "UPDATE uploads SET tags = ? WHERE id = ?",
            (json.dumps(_clean_tags(payload.tags), ensure_ascii=False), existing["id"]),
        )
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

    part = _part_file(upload_id)
    part.parent.mkdir(parents=True, exist_ok=True)
    part.touch()

    conn.execute(
        "INSERT INTO uploads(id, filename, size_bytes, chunk_size, chunk_count, subdir, tags) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            upload_id,
            filename,
            payload.size,
            chunk_size,
            chunk_count,
            payload.subdir.strip("/"),
            json.dumps(_clean_tags(payload.tags), ensure_ascii=False),
        ),
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
        raise HTTPException(status_code=400, detail="Blocknummer liegt außerhalb")

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
                raise HTTPException(status_code=400, detail="Block ist zu groß")
            os.pwrite(handle, piece, offset + written)
            written += len(piece)
    finally:
        os.close(handle)

    if written != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Block unvollständig: {written} statt {expected} Bytes",
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
            detail=f"Upload unvollständig, es fehlen {len(missing)} Blöcke",
        )

    part = _part_file(upload_id)
    if not part.exists() or part.stat().st_size != row["size_bytes"]:
        raise HTTPException(status_code=409, detail="Zwischendatei passt nicht zur Größe")

    target_rel = _target_path(part, row["filename"], row["subdir"])
    destination = settings.media_root / target_rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    # shutil.move statt Path.replace: benennt innerhalb eines Dateisystems nur
    # um und kopiert nur, wenn Quelle und Ziel auf verschiedenen Mounts liegen
    try:
        shutil.move(str(part), str(destination))
    except OSError as exc:
        # Die übertragenen Blöcke bleiben liegen, damit der Upload nach dem
        # Beheben der Ursache ohne erneute Übertragung fertig wird
        log.error("Datei konnte nicht abgelegt werden: %s -> %s (%s)", part, destination, exc)
        raise HTTPException(
            status_code=507 if exc.errno == errno.ENOSPC else 503,
            detail=(
                f"Die Datei konnte nicht in {destination.parent} abgelegt werden: "
                f"{exc.strerror}. Die übertragenen Daten bleiben erhalten, nach dem "
                "Beheben der Ursache genügt ein erneuter Versuch mit derselben Datei."
            ),
        ) from exc
    try:
        os.chmod(destination, 0o664)
    except OSError:
        pass

    stat = destination.stat()
    clip_id, _ = library.upsert_scanned_file(target_rel, stat)
    _apply_tags(clip_id, row["tags"])
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


def _clean_tags(tags: list[str]) -> list[str]:
    seen: list[str] = []
    for tag in tags:
        name = (tag or "").strip()[:60]
        if name and name.lower() not in {s.lower() for s in seen}:
            seen.append(name)
    return seen


def _apply_tags(clip_id: int, raw: str | None) -> None:
    """Vergibt die beim Upload gewählten Tags als manuelle Tags."""
    if not raw:
        return
    try:
        tags = json.loads(raw)
    except (TypeError, ValueError):
        return
    conn = get_conn()
    for name in _clean_tags(tags if isinstance(tags, list) else []):
        tag_id = library.ensure_tag(conn, name, "custom")
        conn.execute(
            "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id, source) "
            "VALUES (?, ?, 'manual')",
            (clip_id, tag_id),
        )
    reindex_fts(conn, clip_id)


def _target_path(temp_file: Path, filename: str, subdir: str) -> str:
    """Bestimmt den Zielpfad, wenn gewünscht direkt einsortiert."""
    if subdir:
        try:
            safe_join(settings.media_root, subdir)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        base = subdir.strip("/")
        return organize.unique_target(base, safe_name(filename), set())

    if not runtime.organize_uploads:
        return organize.unique_target("", safe_name(filename), set())

    try:
        # Dieselbe Regelkette wie beim Scan, damit eine hochgeladene Datei
        # im selben Ordner landet wie eine per NAS-Freigabe kopierte.
        probe = probe_file(temp_file)
        derived = derive(probe, filename, filename)
        return organize.target_for_new_file(filename, probe.recorded_at, derived.camera_label)
    except Exception as exc:  # noqa: BLE001
        log.warning("Einsortieren nicht möglich, Datei landet im Wurzelordner: %s", exc)
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
    """Räumt liegengebliebene Zwischendateien auf (beim Start aufgerufen)."""
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
