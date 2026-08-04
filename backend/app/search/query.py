"""Baut die SQL-Abfrage für die Clip-Suche inklusive Facetten.

Alle Facetten laufen einheitlich über Tags: Kamera, Auflösung, Bildrate,
Look und Herkunft sind automatisch vergebene Tags. Das hält Filterlogik und
Oberfläche einfach, weil es nur einen Mechanismus gibt.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..db import get_conn

SORTS: dict[str, str] = {
    "recorded_desc": "COALESCE(c.recorded_at, c.created_at) DESC, c.id DESC",
    "recorded_asc": "COALESCE(c.recorded_at, c.created_at) ASC, c.id ASC",
    "added_desc": "c.created_at DESC, c.id DESC",
    "duration_desc": "c.duration DESC NULLS LAST, c.id DESC",
    "duration_asc": "c.duration ASC NULLS LAST, c.id ASC",
    "size_desc": "c.size_bytes DESC, c.id DESC",
    "name_asc": "c.filename COLLATE NOCASE ASC, c.id ASC",
}
DEFAULT_SORT = "recorded_desc"


@dataclass
class ClipFilters:
    q: str = ""
    mode: str = "auto"  # auto | text | semantic
    tags: list[str] = field(default_factory=list)
    folder: str = ""
    date_from: str = ""
    date_to: str = ""
    duration_min: float | None = None
    duration_max: float | None = None
    favorite: bool | None = None
    look: str = ""
    collection: int | None = None
    include_missing: bool = False
    only_missing: bool = False
    sort: str = DEFAULT_SORT
    limit: int = 60
    offset: int = 0

    def normalized_sort(self) -> str:
        # Die Reihenfolge innerhalb einer Sammlung steht nicht am Clip, sondern
        # an der Zuordnung. Die Sammlungs-ID ist bereits als int geprüft und
        # wird eingesetzt, damit die Parameterreihenfolge einfach bleibt.
        if self.sort == "collection_pos" and self.collection:
            return (
                f"(SELECT cc.position FROM collection_clips cc "
                f"WHERE cc.collection_id = {int(self.collection)} "
                f"AND cc.clip_id = c.id) ASC, c.id ASC"
            )
        return SORTS.get(self.sort, SORTS[DEFAULT_SORT])


def fts_expression(text: str) -> str | None:
    """Baut aus freiem Text eine FTS5-Abfrage mit Präfixsuche."""
    tokens = [t for t in re.findall(r"[0-9A-Za-zÄÖÜäöüß_]+", text or "") if len(t) > 1]
    if not tokens:
        return None
    return " AND ".join(f'"{token}"*' for token in tokens)


def _tag_conditions(tag_names: list[str]) -> tuple[list[str], list[Any]]:
    """ODER innerhalb einer Kategorie, UND zwischen den Kategorien."""
    if not tag_names:
        return [], []
    conn = get_conn()
    placeholders = ",".join("?" * len(tag_names))
    rows = conn.execute(
        f"SELECT id, name, category FROM tags WHERE name IN ({placeholders})",
        tag_names,
    ).fetchall()
    if not rows:
        # Unbekanntes Tag: es kann keine Treffer geben
        return ["1 = 0"], []

    by_category: dict[str, list[int]] = {}
    for row in rows:
        by_category.setdefault(row["category"], []).append(row["id"])

    clauses: list[str] = []
    params: list[Any] = []
    for ids in by_category.values():
        inner = ",".join("?" * len(ids))
        clauses.append(
            f"c.id IN (SELECT clip_id FROM clip_tags WHERE tag_id IN ({inner}))"
        )
        params.extend(ids)
    return clauses, params


def build_where(filters: ClipFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if filters.only_missing:
        clauses.append("c.status = 'missing'")
    elif not filters.include_missing:
        clauses.append("c.status != 'missing'")

    tag_clauses, tag_params = _tag_conditions(filters.tags)
    clauses.extend(tag_clauses)
    params.extend(tag_params)

    if filters.look:
        clauses.append("COALESCE(c.look_manual, c.look) = ?")
        params.append(filters.look)

    if filters.folder == "/":
        # Sonderfall Wurzelordner: leerer Ordnername in der Datenbank
        clauses.append("c.folder = ''")
    elif filters.folder:
        clauses.append("(c.folder = ? OR c.folder LIKE ?)")
        params.extend([filters.folder, f"{filters.folder}/%"])

    if filters.date_from:
        clauses.append("COALESCE(c.recorded_at, c.created_at) >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append("COALESCE(c.recorded_at, c.created_at) <= ?")
        params.append(filters.date_to + "T23:59:59" if len(filters.date_to) == 10 else filters.date_to)

    if filters.duration_min is not None:
        clauses.append("c.duration >= ?")
        params.append(filters.duration_min)
    if filters.duration_max is not None:
        clauses.append("c.duration <= ?")
        params.append(filters.duration_max)

    if filters.favorite:
        clauses.append("c.favorite = 1")

    if filters.collection:
        clauses.append(
            "c.id IN (SELECT clip_id FROM collection_clips WHERE collection_id = ?)"
        )
        params.append(filters.collection)

    where = " AND ".join(clauses) if clauses else "1 = 1"
    return where, params


def text_match_ids(text: str, limit: int = 5000) -> list[int]:
    expression = fts_expression(text)
    if not expression:
        return []
    rows = get_conn().execute(
        "SELECT clip_id FROM clips_fts WHERE clips_fts MATCH ? "
        "ORDER BY bm25(clips_fts) LIMIT ?",
        (expression, limit),
    ).fetchall()
    return [row["clip_id"] for row in rows]


def facets(where: str, params: list[Any], limit_per_category: int = 40) -> dict:
    """Zählt Tags, Looks und Ordner innerhalb der aktuellen Auswahl."""
    conn = get_conn()
    tag_rows = conn.execute(
        f"""
        SELECT t.name AS name, t.category AS category, COUNT(*) AS count
        FROM clip_tags ct
        JOIN tags t ON t.id = ct.tag_id
        JOIN clips c ON c.id = ct.clip_id
        WHERE {where}
        GROUP BY t.id
        ORDER BY t.category, count DESC, t.name
        """,
        params,
    ).fetchall()

    grouped: dict[str, list[dict]] = {}
    for row in tag_rows:
        bucket = grouped.setdefault(row["category"], [])
        if len(bucket) < limit_per_category:
            bucket.append({"name": row["name"], "count": row["count"]})

    look_rows = conn.execute(
        f"SELECT COALESCE(c.look_manual, c.look) AS look, COUNT(*) AS count "
        f"FROM clips c WHERE {where} GROUP BY look ORDER BY count DESC",
        params,
    ).fetchall()

    folder_rows = conn.execute(
        f"SELECT c.folder AS folder, COUNT(*) AS count FROM clips c WHERE {where} "
        f"GROUP BY c.folder ORDER BY count DESC LIMIT 80",
        params,
    ).fetchall()

    return {
        "tags": grouped,
        "looks": [
            {"name": row["look"] or "unknown", "count": row["count"]}
            for row in look_rows
        ],
        "folders": [
            {"name": row["folder"], "count": row["count"]} for row in folder_rows
        ],
    }
