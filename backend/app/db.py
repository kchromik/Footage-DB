"""SQLite-Zugriff.

Jeder Thread bekommt seine eigene Verbindung. WAL erlaubt gleichzeitige Leser
waehrend ein Worker schreibt, deshalb kommen wir ohne eigene Sperren aus.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

_local = threading.local()
SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def _connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        settings.db_path,
        timeout=30.0,
        isolation_level=None,  # Autocommit, Transaktionen steuern wir selbst
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = _connect()
        _local.conn = conn
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    conn = get_conn()
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db() -> None:
    conn = get_conn()
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _apply_migrations(conn)
    # Haengengebliebene Jobs aus einem harten Neustart wieder freigeben
    conn.execute("UPDATE jobs SET state='queued', started_at=NULL WHERE state='running'")
    log.info("Datenbank bereit: %s", settings.db_path)


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Spaltenweise Nachruestung, damit Updates ohne Datenverlust laufen."""
    additions: dict[str, dict[str, str]] = {
        "clips": {
            "projection": "TEXT",
            "stereo_mode": "TEXT",
        },
        "uploads": {
            "tags": "TEXT",
        },
    }
    for table, columns in additions.items():
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if not existing:
            continue  # Tabelle gibt es noch nicht, schema.sql legt sie komplett an
        for column, ddl in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
                log.info("Spalte %s.%s ergaenzt", table, column)


# --- kleine Helfer ------------------------------------------------------


def query(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    return get_conn().execute(sql, tuple(params)).fetchall()


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    return get_conn().execute(sql, tuple(params)).fetchone()


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    return get_conn().execute(sql, tuple(params))


def scalar(sql: str, params: Iterable[Any] = (), default: Any = None) -> Any:
    row = query_one(sql, params)
    if row is None:
        return default
    value = row[0]
    return default if value is None else value


def get_setting(key: str, default: str | None = None) -> str | None:
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    execute(
        "INSERT INTO settings(key, value, updated_at) VALUES (?, ?, datetime('now')) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, value),
    )


def reindex_fts(conn: sqlite3.Connection, clip_id: int) -> None:
    """Baut den Volltext-Eintrag eines Clips neu auf."""
    row = conn.execute(
        "SELECT path, filename, original_filename, folder, camera_make, camera_model, "
        "camera_label, lens, title, notes, look, video_codec, container "
        "FROM clips WHERE id = ?",
        (clip_id,),
    ).fetchone()
    if row is None:
        conn.execute("DELETE FROM clips_fts WHERE clip_id = ?", (clip_id,))
        return

    tags = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM tags t JOIN clip_tags ct ON ct.tag_id = t.id "
            "WHERE ct.clip_id = ?",
            (clip_id,),
        )
    ]

    parts: list[str] = []
    for key in (
        "filename",
        "original_filename",
        "folder",
        "camera_make",
        "camera_model",
        "camera_label",
        "lens",
        "title",
        "notes",
        "look",
        "video_codec",
        "container",
    ):
        value = row[key]
        if value:
            parts.append(str(value))
    parts.extend(tags)

    # Dateinamen zusaetzlich an Trennzeichen zerlegen, damit "A7401" auch
    # in "2026-07-14_FX3_A7401.MP4" gefunden wird
    import re

    tokens = set()
    for value in (row["filename"], row["original_filename"], row["folder"]):
        if value:
            tokens.update(t for t in re.split(r"[^0-9A-Za-zÄÖÜäöüß]+", str(value)) if t)
    parts.extend(sorted(tokens))

    body = " ".join(parts)
    conn.execute("DELETE FROM clips_fts WHERE clip_id = ?", (clip_id,))
    conn.execute("INSERT INTO clips_fts(body, clip_id) VALUES (?, ?)", (body, clip_id))
