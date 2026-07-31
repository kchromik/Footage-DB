"""Sammlungen: Clips für ein bestimmtes Videoprojekt zusammenstellen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_conn
from ..serializers import load_tags, serialize_clip
from .deps import require_user

router = APIRouter(
    prefix="/api/collections", tags=["collections"], dependencies=[Depends(require_user)]
)


class CollectionIn(BaseModel):
    name: str
    notes: str | None = None


@router.get("")
def list_collections() -> dict:
    rows = get_conn().execute(
        "SELECT c.id, c.name, c.notes, c.created_at, COUNT(cc.clip_id) AS count "
        "FROM collections c LEFT JOIN collection_clips cc ON cc.collection_id = c.id "
        "GROUP BY c.id ORDER BY c.created_at DESC"
    ).fetchall()
    return {"items": [dict(row) for row in rows]}


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
    return {"id": cursor.lastrowid, "name": name, "notes": payload.notes, "count": 0}


@router.get("/{collection_id}")
def get_collection(collection_id: int) -> dict:
    conn = get_conn()
    collection = conn.execute(
        "SELECT * FROM collections WHERE id = ?", (collection_id,)
    ).fetchone()
    if collection is None:
        raise HTTPException(status_code=404, detail="Sammlung nicht gefunden")
    rows = conn.execute(
        "SELECT c.* FROM collection_clips cc JOIN clips c ON c.id = cc.clip_id "
        "WHERE cc.collection_id = ? ORDER BY cc.position, cc.added_at",
        (collection_id,),
    ).fetchall()
    tag_map = load_tags([row["id"] for row in rows])
    return {
        **dict(collection),
        "items": [serialize_clip(row, tag_map.get(row["id"], [])) for row in rows],
    }


class MembersRequest(BaseModel):
    clip_ids: list[int]


@router.post("/{collection_id}/clips")
def add_clips(collection_id: int, payload: MembersRequest) -> dict:
    conn = get_conn()
    if conn.execute("SELECT id FROM collections WHERE id = ?", (collection_id,)).fetchone() is None:
        raise HTTPException(status_code=404, detail="Sammlung nicht gefunden")
    position = conn.execute(
        "SELECT COALESCE(MAX(position), 0) AS p FROM collection_clips WHERE collection_id = ?",
        (collection_id,),
    ).fetchone()["p"]
    added = 0
    for clip_id in payload.clip_ids:
        position += 1
        cursor = conn.execute(
            "INSERT OR IGNORE INTO collection_clips(collection_id, clip_id, position) "
            "VALUES (?, ?, ?)",
            (collection_id, clip_id, position),
        )
        added += cursor.rowcount or 0
    return {"added": added}


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
