"""Schreibender Zugriff auf die Clip-Tabelle: anlegen, aktualisieren, taggen."""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path, PurePosixPath

from . import jobs, paths
from .config import settings
from .db import get_conn, reindex_fts
from .events import bus
from .metadata.probe import ProbeResult
from .metadata.rules import Derived
from .util import content_hash, iso

log = logging.getLogger(__name__)

AUTO_TAG_SOURCE = "auto"


# --- Tags ---------------------------------------------------------------


def ensure_tag(conn: sqlite3.Connection, name: str, category: str = "custom") -> int:
    name = name.strip()
    row = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        "INSERT INTO tags(name, category) VALUES (?, ?)", (name, category)
    )
    return int(cursor.lastrowid)


def set_auto_tags(
    conn: sqlite3.Connection, clip_id: int, tags: list[tuple[str, str]]
) -> None:
    """Ersetzt alle automatischen Tags eines Clips. Manuelle bleiben unberuehrt."""
    conn.execute(
        "DELETE FROM clip_tags WHERE clip_id = ? AND source = ?",
        (clip_id, AUTO_TAG_SOURCE),
    )
    for name, category in tags:
        tag_id = ensure_tag(conn, name, category)
        conn.execute(
            "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id, source) VALUES (?, ?, ?)",
            (clip_id, tag_id, AUTO_TAG_SOURCE),
        )


def cleanup_orphan_tags(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        "DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag_id FROM clip_tags)"
    )
    return cursor.rowcount


# --- Clips --------------------------------------------------------------


def _folder_of(rel_path: str) -> str:
    parent = PurePosixPath(rel_path).parent
    return "" if str(parent) == "." else str(parent)


def upsert_scanned_file(rel_path: str, stat: os.stat_result) -> tuple[int, str]:
    """Legt einen Clip an oder aktualisiert ihn.

    Liefert (clip_id, aktion) mit aktion aus new|updated|moved|unchanged.
    """
    conn = get_conn()
    filename = PurePosixPath(rel_path).name
    ext = PurePosixPath(rel_path).suffix.lower()
    now_seen = "datetime('now')"

    row = conn.execute(
        "SELECT id, size_bytes, mtime, status FROM clips WHERE path = ?", (rel_path,)
    ).fetchone()

    if row is not None:
        unchanged = (
            row["size_bytes"] == stat.st_size
            and abs(row["mtime"] - stat.st_mtime) < 1.0
            and row["status"] not in ("missing", "new")
        )
        if unchanged:
            conn.execute(
                f"UPDATE clips SET seen_at = {now_seen}, status = 'indexed' WHERE id = ?",
                (row["id"],),
            )
            return row["id"], "unchanged"

        digest = _safe_hash(rel_path, stat.st_size)
        conn.execute(
            f"UPDATE clips SET size_bytes=?, mtime=?, content_hash=?, status='new', "
            f"error=NULL, seen_at={now_seen}, updated_at={now_seen} WHERE id=?",
            (stat.st_size, stat.st_mtime, digest, row["id"]),
        )
        jobs.enqueue("probe", row["id"], conn=conn)
        return row["id"], "updated"

    # Neuer Pfad: eventuell nur verschoben oder umbenannt
    digest = _safe_hash(rel_path, stat.st_size)
    if digest:
        candidate = conn.execute(
            "SELECT id, path FROM clips WHERE content_hash = ? AND size_bytes = ? "
            "ORDER BY id LIMIT 1",
            (digest, stat.st_size),
        ).fetchone()
        if candidate and not (settings.media_root / candidate["path"]).exists():
            conn.execute(
                f"UPDATE clips SET path=?, filename=?, folder=?, ext=?, mtime=?, "
                f"status='indexed', seen_at={now_seen}, updated_at={now_seen} WHERE id=?",
                (
                    rel_path,
                    filename,
                    _folder_of(rel_path),
                    ext,
                    stat.st_mtime,
                    candidate["id"],
                ),
            )
            reindex_fts(conn, candidate["id"])
            log.info("Datei erkannt als verschoben: %s -> %s", candidate["path"], rel_path)
            return candidate["id"], "moved"

    cursor = conn.execute(
        f"INSERT INTO clips(path, filename, original_filename, folder, ext, size_bytes, "
        f"mtime, content_hash, status, seen_at) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'new', {now_seen})",
        (
            rel_path,
            filename,
            filename,
            _folder_of(rel_path),
            ext,
            stat.st_size,
            stat.st_mtime,
            digest,
        ),
    )
    clip_id = int(cursor.lastrowid)
    reindex_fts(conn, clip_id)
    jobs.enqueue("probe", clip_id, conn=conn)
    return clip_id, "new"


def _safe_hash(rel_path: str, size: int) -> str | None:
    try:
        return content_hash(settings.media_root / rel_path, size)
    except OSError as exc:
        log.warning("Konnte Pruefsumme nicht bilden fuer %s: %s", rel_path, exc)
        return None


def apply_probe(clip_id: int, probe: ProbeResult, derived: Derived) -> None:
    """Schreibt Probe-Ergebnis und abgeleitete Werte in die Datenbank."""
    conn = get_conn()
    conn.execute(
        """
        UPDATE clips SET
            duration=?, width=?, height=?, fps=?, video_codec=?, audio_codec=?,
            audio_channels=?, pix_fmt=?, bit_depth=?, color_transfer=?,
            color_primaries=?, color_space=?, bitrate=?, rotation=?, container=?,
            encoder=?, camera_make=?, camera_model=?, camera_label=?, lens=?,
            recorded_at=?, recorded_source=?, gps_lat=?, gps_lon=?,
            look=?, look_reason=?,
            status='indexed', error=NULL,
            indexed_at=datetime('now'), updated_at=datetime('now')
        WHERE id=?
        """,
        (
            probe.duration,
            probe.width,
            probe.height,
            probe.fps,
            probe.video_codec,
            probe.audio_codec,
            probe.audio_channels,
            probe.pix_fmt,
            probe.bit_depth,
            probe.color_transfer,
            probe.color_primaries,
            probe.color_space,
            probe.bitrate,
            probe.rotation,
            probe.container,
            probe.encoder,
            probe.camera_make,
            probe.camera_model,
            derived.camera_label,
            probe.lens,
            iso(probe.recorded_at),
            probe.recorded_source,
            probe.gps_lat,
            probe.gps_lon,
            derived.look,
            derived.look_reason,
            clip_id,
        ),
    )
    set_auto_tags(conn, clip_id, derived.tags)
    reindex_fts(conn, clip_id)
    bus.publish("clip", id=clip_id, action="indexed")


def mark_missing(rel_paths: list[str]) -> int:
    if not rel_paths:
        return 0
    conn = get_conn()
    placeholders = ",".join("?" * len(rel_paths))
    cursor = conn.execute(
        f"UPDATE clips SET status='missing', updated_at=datetime('now') "
        f"WHERE path IN ({placeholders})",
        rel_paths,
    )
    return cursor.rowcount


def delete_clip(clip_id: int, remove_file: bool = False) -> None:
    conn = get_conn()
    row = conn.execute("SELECT path FROM clips WHERE id=?", (clip_id,)).fetchone()
    if row is None:
        return
    if remove_file:
        try:
            (settings.media_root / row["path"]).unlink(missing_ok=True)
        except OSError as exc:
            log.warning("Datei konnte nicht geloescht werden: %s", exc)
    for artifact in paths.artifact_paths(clip_id):
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            pass
    conn.execute("DELETE FROM clips_fts WHERE clip_id=?", (clip_id,))
    conn.execute("DELETE FROM clips WHERE id=?", (clip_id,))
    bus.publish("clip", id=clip_id, action="deleted")


def update_path(clip_id: int, new_rel_path: str) -> None:
    conn = get_conn()
    name = PurePosixPath(new_rel_path).name
    conn.execute(
        "UPDATE clips SET path=?, filename=?, folder=?, ext=?, updated_at=datetime('now') "
        "WHERE id=?",
        (
            new_rel_path,
            name,
            _folder_of(new_rel_path),
            PurePosixPath(new_rel_path).suffix.lower(),
            clip_id,
        ),
    )
    reindex_fts(conn, clip_id)


def cleanup_orphan_artifacts() -> int:
    """Entfernt Thumbnails und Proxies, zu denen es keinen Clip mehr gibt."""
    conn = get_conn()
    known = {row["id"] for row in conn.execute("SELECT id FROM clips")}
    removed = 0
    for base in (settings.thumbs_dir, settings.proxies_dir):
        if not base.exists():
            continue
        for file in base.rglob("*"):
            if not file.is_file():
                continue
            stem = file.stem.split("_")[0]
            if not stem.isdigit() or int(stem) in known:
                continue
            try:
                file.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def clip_source(clip_id: int) -> Path | None:
    row = get_conn().execute("SELECT path FROM clips WHERE id=?", (clip_id,)).fetchone()
    if row is None:
        return None
    return settings.media_root / row["path"]
