"""Suche, Detailansicht und Bearbeitung von Clips."""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .. import jobs, library
from ..config import settings
from ..db import get_conn, reindex_fts
from ..search import query as q
from ..search import semantic
from ..serializers import load_tags, serialize_clip
from ..settings_store import runtime
from .deps import require_user

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/clips", tags=["clips"], dependencies=[Depends(require_user)])

SEMANTIC_THRESHOLD = 0.19
SEMANTIC_POOL = 400


def _filters(
    q_text: str,
    mode: str,
    tags: list[str],
    folder: str,
    look: str,
    date_from: str,
    date_to: str,
    duration_min: float | None,
    duration_max: float | None,
    favorite: bool,
    only_missing: bool,
    include_missing: bool,
    sort: str,
    limit: int,
    offset: int,
) -> q.ClipFilters:
    return q.ClipFilters(
        q=q_text.strip(),
        mode=mode,
        tags=[t for t in tags if t.strip()],
        folder=folder.strip(),
        look=look.strip(),
        date_from=date_from.strip(),
        date_to=date_to.strip(),
        duration_min=duration_min,
        duration_max=duration_max,
        favorite=favorite or None,
        only_missing=only_missing,
        include_missing=include_missing,
        sort=sort,
        limit=max(1, min(limit, 200)),
        offset=max(0, offset),
    )


@router.get("")
def list_clips(
    q_text: str = Query("", alias="q"),
    mode: Literal["auto", "text", "semantic"] = "auto",
    tags: list[str] = Query(default=[], alias="tag"),
    folder: str = "",
    look: str = "",
    date_from: str = "",
    date_to: str = "",
    duration_min: float | None = None,
    duration_max: float | None = None,
    favorite: bool = False,
    only_missing: bool = False,
    include_missing: bool = False,
    sort: str = q.DEFAULT_SORT,
    limit: int = 60,
    offset: int = 0,
    with_facets: bool = False,
) -> dict:
    filters = _filters(
        q_text, mode, tags, folder, look, date_from, date_to,
        duration_min, duration_max, favorite, only_missing, include_missing,
        sort, limit, offset,
    )
    where, params = q.build_where(filters)
    conn = get_conn()

    ranked: list[tuple[int, float]] | None = None
    used_mode = "filter"

    if filters.q:
        text_ids = q.text_match_ids(filters.q)
        semantic_hits: list[tuple[int, float]] = []
        wants_semantic = filters.mode in ("auto", "semantic") and runtime.semantic_enabled
        if wants_semantic and (filters.mode == "semantic" or len(text_ids) < 25):
            semantic_hits = semantic.search(filters.q, limit=SEMANTIC_POOL)
            semantic_hits = [
                (cid, score) for cid, score in semantic_hits if score >= SEMANTIC_THRESHOLD
            ]

        if filters.mode == "semantic":
            ranked = semantic_hits
            used_mode = "semantic"
        elif filters.mode == "text" or not semantic_hits:
            ranked = [(cid, 1.0 - i / 10000) for i, cid in enumerate(text_ids)]
            used_mode = "text"
        else:
            # Exakte Treffer zuerst, danach die inhaltlich ähnlichen
            seen = set(text_ids)
            ranked = [(cid, 2.0 - i / 10000) for i, cid in enumerate(text_ids)]
            ranked += [(cid, score) for cid, score in semantic_hits if cid not in seen]
            used_mode = "hybrid"

        if not ranked:
            return {
                "items": [],
                "total": 0,
                "offset": filters.offset,
                "limit": filters.limit,
                "mode": used_mode,
                "facets": {"tags": {}, "looks": [], "folders": []} if with_facets else None,
            }

    if ranked is not None:
        ids = [cid for cid, _ in ranked]
        scores = dict(ranked)
        placeholders = ",".join("?" * len(ids))
        rows = conn.execute(
            f"SELECT c.* FROM clips c WHERE {where} AND c.id IN ({placeholders})",
            [*params, *ids],
        ).fetchall()
        rows.sort(key=lambda r: -scores.get(r["id"], 0.0))
        total = len(rows)
        page = rows[filters.offset : filters.offset + filters.limit]
        facet_where = f"{where} AND c.id IN ({placeholders})"
        facet_params = [*params, *ids]
    else:
        total = conn.execute(
            f"SELECT COUNT(*) AS n FROM clips c WHERE {where}", params
        ).fetchone()["n"]
        page = conn.execute(
            f"SELECT c.* FROM clips c WHERE {where} ORDER BY {filters.normalized_sort()} "
            f"LIMIT ? OFFSET ?",
            [*params, filters.limit, filters.offset],
        ).fetchall()
        scores = {}
        facet_where, facet_params = where, params

    tag_map = load_tags([row["id"] for row in page])
    items = [
        serialize_clip(row, tag_map.get(row["id"], []), scores.get(row["id"]))
        for row in page
    ]

    return {
        "items": items,
        "total": total,
        "offset": filters.offset,
        "limit": filters.limit,
        "mode": used_mode,
        "facets": q.facets(facet_where, facet_params) if with_facets else None,
    }


@router.get("/{clip_id}")
def get_clip(clip_id: int) -> dict:
    row = get_conn().execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Clip nicht gefunden")
    data = serialize_clip(row, load_tags([clip_id]).get(clip_id, []))
    data["neighbours"] = _neighbours(clip_id)
    return data


def _neighbours(clip_id: int) -> dict:
    conn = get_conn()
    previous = conn.execute(
        "SELECT id FROM clips WHERE id < ? AND status != 'missing' ORDER BY id DESC LIMIT 1",
        (clip_id,),
    ).fetchone()
    following = conn.execute(
        "SELECT id FROM clips WHERE id > ? AND status != 'missing' ORDER BY id ASC LIMIT 1",
        (clip_id,),
    ).fetchone()
    return {
        "previous": previous["id"] if previous else None,
        "next": following["id"] if following else None,
    }


class ClipUpdate(BaseModel):
    title: str | None = None
    notes: str | None = None
    favorite: bool | None = None
    rating: int | None = Field(default=None, ge=0, le=5)
    look_manual: str | None = None
    tags: list[str] | None = None


ALLOWED_LOOKS = {"log", "rec709", "hdr", "graded", "unknown", ""}


@router.patch("/{clip_id}")
def update_clip(clip_id: int, payload: ClipUpdate) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Clip nicht gefunden")

    updates: dict[str, Any] = {}
    if payload.title is not None:
        updates["title"] = payload.title.strip() or None
    if payload.notes is not None:
        updates["notes"] = payload.notes.strip() or None
    if payload.favorite is not None:
        updates["favorite"] = int(payload.favorite)
    if payload.rating is not None:
        updates["rating"] = payload.rating
    if payload.look_manual is not None:
        value = payload.look_manual.strip().lower()
        if value not in ALLOWED_LOOKS:
            raise HTTPException(status_code=400, detail=f"Unbekannter Look: {value}")
        updates["look_manual"] = value or None

    if updates:
        assignments = ", ".join(f"{key} = ?" for key in updates)
        conn.execute(
            f"UPDATE clips SET {assignments}, updated_at = datetime('now') WHERE id = ?",
            [*updates.values(), clip_id],
        )

    if payload.tags is not None:
        _replace_manual_tags(clip_id, payload.tags)

    reindex_fts(conn, clip_id)
    updated = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    return serialize_clip(updated, load_tags([clip_id]).get(clip_id, []))


def _replace_manual_tags(clip_id: int, names: list[str]) -> None:
    conn = get_conn()
    conn.execute(
        "DELETE FROM clip_tags WHERE clip_id = ? AND source = 'manual'", (clip_id,)
    )
    for name in names:
        name = name.strip()
        if not name:
            continue
        tag_id = library.ensure_tag(conn, name, "custom")
        conn.execute(
            "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id, source) "
            "VALUES (?, ?, 'manual')",
            (clip_id, tag_id),
        )


class BatchTagRequest(BaseModel):
    clip_ids: list[int]
    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)
    favorite: bool | None = None
    look_manual: str | None = None


@router.post("/batch/tags")
def batch_tags(payload: BatchTagRequest) -> dict:
    if not payload.clip_ids:
        raise HTTPException(status_code=400, detail="Keine Clips ausgewählt")
    conn = get_conn()
    changed = 0
    for clip_id in payload.clip_ids:
        exists = conn.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if exists is None:
            continue
        for name in payload.add:
            name = name.strip()
            if not name:
                continue
            tag_id = library.ensure_tag(conn, name, "custom")
            conn.execute(
                "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id, source) "
                "VALUES (?, ?, 'manual')",
                (clip_id, tag_id),
            )
        for name in payload.remove:
            conn.execute(
                "DELETE FROM clip_tags WHERE clip_id = ? AND source = 'manual' AND "
                "tag_id IN (SELECT id FROM tags WHERE name = ?)",
                (clip_id, name.strip()),
            )
        if payload.favorite is not None:
            conn.execute(
                "UPDATE clips SET favorite = ? WHERE id = ?",
                (int(payload.favorite), clip_id),
            )
        if payload.look_manual is not None:
            value = payload.look_manual.strip().lower()
            if value not in ALLOWED_LOOKS:
                raise HTTPException(status_code=400, detail=f"Unbekannter Look: {value}")
            conn.execute(
                "UPDATE clips SET look_manual = ? WHERE id = ?", (value or None, clip_id)
            )
        conn.execute(
            "UPDATE clips SET updated_at = datetime('now') WHERE id = ?", (clip_id,)
        )
        reindex_fts(conn, clip_id)
        changed += 1
    return {"changed": changed}


@router.post("/{clip_id}/reprocess")
def reprocess(clip_id: int, what: str = Body("all", embed=True)) -> dict:
    conn = get_conn()
    row = conn.execute("SELECT id FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Clip nicht gefunden")
    mapping = {
        "all": ["probe"],
        "metadata": ["probe"],
        "poster": ["poster"],
        "proxy": ["proxy"],
        "sprite": ["sprite"],
        "embed": ["embed"],
    }
    types = mapping.get(what, ["probe"])
    for job_type in types:
        jobs.enqueue(job_type, clip_id)
    return {"queued": types}


@router.delete("/{clip_id}")
def delete_clip(clip_id: int, remove_file: bool = False) -> dict:
    library.delete_clip(clip_id, remove_file=remove_file)
    semantic.index.remove(clip_id)
    return {"ok": True, "file_removed": remove_file}
