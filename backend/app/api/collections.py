"""Sammlungen: Clips für ein bestimmtes Videoprojekt zusammenstellen.

Ein Clip darf in beliebig vielen Sammlungen liegen, die Zuordnung steht in
einer eigenen Tabelle. Nichts wird kopiert oder verschoben.
"""

from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_conn
from .deps import require_user

router = APIRouter(
    prefix="/api/collections", tags=["collections"], dependencies=[Depends(require_user)]
)


class CollectionIn(BaseModel):
    name: str
    notes: str | None = None


class CollectionPatch(BaseModel):
    name: str | None = None
    notes: str | None = None


LIST_SQL = """
    SELECT c.id, c.name, c.notes, c.created_at,
           COUNT(cc.clip_id) AS count,
           (SELECT cl.id FROM collection_clips m
              JOIN clips cl ON cl.id = m.clip_id
             WHERE m.collection_id = c.id AND cl.poster_status = 'ready'
             ORDER BY m.position, m.added_at LIMIT 1) AS cover_id
      FROM collections c
      LEFT JOIN collection_clips cc ON cc.collection_id = c.id
"""


def _row_to_dict(row: sqlite3.Row) -> dict:
    data = dict(row)
    cover = data.pop("cover_id", None)
    data["cover_url"] = f"/api/media/{cover}/poster" if cover else None
    return data


@router.get("")
def list_collections() -> dict:
    rows = get_conn().execute(
        f"{LIST_SQL} GROUP BY c.id ORDER BY c.name COLLATE NOCASE"
    ).fetchall()
    return {"items": [_row_to_dict(row) for row in rows]}


@router.post("")
def create_collection(payload: CollectionIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name fehlt")
    conn = get_conn()
    if conn.execute("SELECT id FROM collections WHERE name = ?", (name,)).fetchone():
        raise HTTPException(status_code=409, detail="Diese Sammlung gibt es schon")
    cursor = conn.execute(
        "INSERT INTO collections(name, notes) VALUES (?, ?)", (name, payload.notes)
    )
    return _one(int(cursor.lastrowid))


def _one(collection_id: int) -> dict:
    row = get_conn().execute(
        f"{LIST_SQL} WHERE c.id = ? GROUP BY c.id", (collection_id,)
    ).fetchone()
    if row is None or row["id"] is None:
        raise HTTPException(status_code=404, detail="Sammlung nicht gefunden")
    return _row_to_dict(row)


@router.get("/{collection_id}")
def get_collection(collection_id: int) -> dict:
    """Nur die Sammlung selbst.

    Die Clips holt die Oberfläche über die normale Clip-Liste mit
    `collection=<id>`, damit Suche, Filter und Sortierung auch innerhalb
    einer Sammlung funktionieren.
    """
    return _one(collection_id)


@router.patch("/{collection_id}")
def update_collection(collection_id: int, payload: CollectionPatch) -> dict:
    conn = get_conn()
    _one(collection_id)
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Name fehlt")
        clash = conn.execute(
            "SELECT id FROM collections WHERE name = ? AND id != ?", (name, collection_id)
        ).fetchone()
        if clash:
            raise HTTPException(status_code=409, detail="Diese Sammlung gibt es schon")
        conn.execute("UPDATE collections SET name = ? WHERE id = ?", (name, collection_id))
    if payload.notes is not None:
        conn.execute(
            "UPDATE collections SET notes = ? WHERE id = ?",
            (payload.notes.strip() or None, collection_id),
        )
    return _one(collection_id)


class MembersRequest(BaseModel):
    clip_ids: list[int]


@router.post("/{collection_id}/clips")
def add_clips(collection_id: int, payload: MembersRequest) -> dict:
    conn = get_conn()
    _one(collection_id)
    position = conn.execute(
        "SELECT COALESCE(MAX(position), 0) AS p FROM collection_clips WHERE collection_id = ?",
        (collection_id,),
    ).fetchone()["p"]
    added = 0
    for clip_id in payload.clip_ids:
        # Unbekannte IDs überspringen, sonst bricht der Fremdschlüssel den
        # ganzen Stapel ab, nur weil ein Clip zwischenzeitlich weg ist.
        if conn.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone() is None:
            continue
        position += 1
        cursor = conn.execute(
            "INSERT OR IGNORE INTO collection_clips(collection_id, clip_id, position) "
            "VALUES (?, ?, ?)",
            (collection_id, clip_id, position),
        )
        added += cursor.rowcount or 0
    return {"added": added, "collection": _one(collection_id)}


@router.delete("/{collection_id}/clips")
def remove_clips(collection_id: int, payload: MembersRequest) -> dict:
    conn = get_conn()
    placeholders = ",".join("?" * len(payload.clip_ids)) or "NULL"
    cursor = conn.execute(
        f"DELETE FROM collection_clips WHERE collection_id = ? AND clip_id IN ({placeholders})",
        [collection_id, *payload.clip_ids],
    )
    return {"removed": cursor.rowcount or 0}


@router.delete("/{collection_id}")
def delete_collection(collection_id: int) -> dict:
    conn = get_conn()
    conn.execute("DELETE FROM collection_clips WHERE collection_id = ?", (collection_id,))
    conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
    return {"ok": True}
