"""Gemeinsame Testhelfer."""

from __future__ import annotations

from app.db import get_conn, reindex_fts


def insert_clip(path: str, **columns) -> int:
    """Legt einen Clip direkt in der Datenbank an, ohne echte Datei."""
    conn = get_conn()
    values = {
        "path": path,
        "filename": path.rsplit("/", 1)[-1],
        "folder": path.rsplit("/", 1)[0] if "/" in path else "",
        "ext": ".mp4",
        "size_bytes": 1000,
        "mtime": 0.0,
        "status": "indexed",
        "look": "rec709",
        "duration": 10.0,
        "width": 1920,
        "height": 1080,
    }
    values.update(columns)
    names = ",".join(values)
    marks = ",".join("?" * len(values))
    cursor = conn.execute(f"INSERT INTO clips({names}) VALUES ({marks})", list(values.values()))
    clip_id = int(cursor.lastrowid)
    reindex_fts(conn, clip_id)
    return clip_id
