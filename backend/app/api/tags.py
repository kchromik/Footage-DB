"""Verwaltung der Tags."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_conn, reindex_fts
from .deps import require_user

router = APIRouter(prefix="/api/tags", tags=["tags"], dependencies=[Depends(require_user)])


@router.get("")
def list_tags(category: str = "", min_count: int = 1) -> dict:
    conn = get_conn()
    sql = (
        "SELECT t.id, t.name, t.category, t.color, COUNT(ct.clip_id) AS count "
        "FROM tags t LEFT JOIN clip_tags ct ON ct.tag_id = t.id "
        "LEFT JOIN clips c ON c.id = ct.clip_id AND c.status != 'missing' "
    )
    params: list = []
    if category:
        sql += "WHERE t.category = ? "
        params.append(category)
    sql += "GROUP BY t.id HAVING count >= ? ORDER BY t.category, count DESC, t.name"
    params.append(min_count)

    rows = conn.execute(sql, params).fetchall()
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(row["category"], []).append(dict(row))
    return {"items": [dict(row) for row in rows], "by_category": grouped}


class TagUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
    category: str | None = None


@router.patch("/{tag_id}")
def update_tag(tag_id: int, payload: TagUpdate) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Tag nicht gefunden")

    updates = {}
    if payload.name and payload.name.strip():
        exists = conn.execute(
            "SELECT id FROM tags WHERE name = ? AND id != ?",
            (payload.name.strip(), tag_id),
        ).fetchone()
        if exists:
            raise HTTPException(status_code=409, detail="Dieser Name ist schon vergeben")
        updates["name"] = payload.name.strip()
    if payload.color is not None:
        updates["color"] = payload.color.strip() or None
    if payload.category:
        updates["category"] = payload.category.strip()

    if updates:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE tags SET {assignments} WHERE id = ?", [*updates.values(), tag_id]
        )
        for clip in conn.execute(
            "SELECT clip_id FROM clip_tags WHERE tag_id = ?", (tag_id,)
        ).fetchall():
            reindex_fts(conn, clip["clip_id"])

    updated = conn.execute("SELECT * FROM tags WHERE id = ?", (tag_id,)).fetchone()
    return dict(updated)


@router.delete("/{tag_id}")
def delete_tag(tag_id: int) -> dict:
    conn = get_conn()
    clips = [
        row["clip_id"]
        for row in conn.execute(
            "SELECT clip_id FROM clip_tags WHERE tag_id = ?", (tag_id,)
        ).fetchall()
    ]
    conn.execute("DELETE FROM clip_tags WHERE tag_id = ?", (tag_id,))
    conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
    for clip_id in clips:
        reindex_fts(conn, clip_id)
    return {"ok": True, "affected_clips": len(clips)}
