"""Vorschläge für das Suchfeld.

Warum eigene Abfragen und nicht der Volltextindex: Vorgeschlagen wird nicht
der Treffer, sondern der Weg dahin. Wer "rasp" tippt, soll das Tag
"Raspberry Pi" angeboten bekommen und mit einem Klick als Filter setzen,
statt denselben Text als Volltextsuche loszuschicken. Deshalb liefert diese
Datei genau die Dinge, die es auch im Filterbereich links gibt: Tags jeder
Kategorie (Kamera, Objektiv, Technik, Herkunft, eigene), Ordner, Bildlook,
Sammlungen und den Schnellzugriff. Dazu kommen Dateinamen, damit man einen
bekannten Clip direkt aufmachen kann.

Tags und Sammlungen werden in Python gefiltert und nicht per LIKE: SQLite
vergleicht bei LIKE nur ASCII ohne Rücksicht auf Groß- und Kleinschreibung,
"öl" fände also "Ölwanne" nicht. Die Tabellen sind klein genug dafür.
"""

from __future__ import annotations

import re
from typing import Any

from ..db import get_conn

# Anzeigenamen der Gruppen. Sie stehen bewusst hier und nicht in der
# Oberfläche, damit ein neuer Vorschlagstyp nur an einer Stelle entsteht.
CATEGORY_GROUP = {
    "camera": "Kamera",
    "lens": "Objektiv",
    "tech": "Technik",
    "source": "Herkunft",
    "look": "Look",
    "custom": "Eigene Tags",
}

LOOK_LABEL = {
    "log": "LOG",
    "graded": "Graded",
    "hdr": "HDR",
    "rec709": "Rec.709",
}

# Wie viele Einträge eine Gruppe höchstens beisteuert
CAPS = {
    "tag": 8,
    "folder": 3,
    "clip": 5,
    "collection": 3,
    "look": 2,
    "quick": 2,
}


def _like(text: str) -> str:
    """Baut ein LIKE-Muster und entschärft die Platzhalterzeichen."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _rank(name: str, needle: str) -> int:
    """0 = Anfang des Namens, 1 = Anfang eines Wortes, 2 = irgendwo drin."""
    haystack = name.casefold()
    if haystack.startswith(needle):
        return 0
    if re.search(r"(?:^|[^0-9a-zäöüß])" + re.escape(needle), haystack):
        return 1
    return 2


def _matches(name: str, needle: str) -> bool:
    return needle in name.casefold()


def suggest(text: str, limit: int = 14) -> list[dict]:
    needle = (text or "").strip().casefold()
    if len(needle) < 1:
        return []

    conn = get_conn()
    candidates: list[dict[str, Any]] = []
    candidates += _tags(conn, needle)
    candidates += _looks(conn, needle)
    candidates += _quick(conn, needle)
    candidates += _folders(conn, needle, text.strip())
    candidates += _collections(conn, needle)
    candidates += _clips(conn, needle, text.strip())

    # Erst je Art deckeln, damit nicht 40 Dateinamen alles andere verdrängen
    per_kind: dict[str, int] = {}
    kept: list[dict] = []
    for item in sorted(candidates, key=lambda i: (i["rank"], -i["count"], i["label"])):
        seen = per_kind.get(item["kind"], 0)
        if seen >= CAPS.get(item["kind"], 5):
            continue
        per_kind[item["kind"]] = seen + 1
        kept.append(item)

    # Gruppen in der Reihenfolge ihres besten Treffers, damit oben steht,
    # was am ehesten gemeint war
    order: dict[str, tuple[int, int]] = {}
    for position, item in enumerate(kept):
        group = item["group"]
        if group not in order:
            order[group] = (item["rank"], position)
    kept.sort(key=lambda i: (order[i["group"]], i["rank"], -i["count"]))

    for item in kept:
        item.pop("rank", None)
    return kept[: max(1, min(limit, 30))]


def _tags(conn, needle: str) -> list[dict]:
    rows = conn.execute("SELECT id, name, category FROM tags").fetchall()
    hits = [row for row in rows if _matches(row["name"], needle)]
    if not hits:
        return []

    # Zählen nur für die Treffer, nicht für den ganzen Tag-Bestand
    placeholders = ",".join("?" * len(hits))
    counts = {
        row["tag_id"]: row["n"]
        for row in conn.execute(
            f"SELECT ct.tag_id AS tag_id, COUNT(*) AS n FROM clip_tags ct "
            f"JOIN clips c ON c.id = ct.clip_id AND c.status != 'missing' "
            f"WHERE ct.tag_id IN ({placeholders}) GROUP BY ct.tag_id",
            [row["id"] for row in hits],
        ).fetchall()
    }

    items = []
    for row in hits:
        count = counts.get(row["id"], 0)
        if count == 0:
            continue  # verwaistes Tag, als Filter wertlos
        items.append(
            {
                "kind": "tag",
                "group": CATEGORY_GROUP.get(row["category"], "Tags"),
                "category": row["category"],
                "value": row["name"],
                "label": row["name"],
                "detail": None,
                "count": count,
                "clip_id": None,
                "rank": _rank(row["name"], needle),
            }
        )
    return items


def _looks(conn, needle: str) -> list[dict]:
    rows = conn.execute(
        "SELECT COALESCE(look_manual, look) AS look, COUNT(*) AS n FROM clips "
        "WHERE status != 'missing' GROUP BY look"
    ).fetchall()
    items = []
    for row in rows:
        key = row["look"] or "unknown"
        label = LOOK_LABEL.get(key)
        if not label or not (_matches(label, needle) or _matches(key, needle)):
            continue
        items.append(
            {
                "kind": "look",
                "group": "Bildlook",
                "category": "look",
                "value": key,
                "label": label,
                "detail": None,
                "count": row["n"],
                "clip_id": None,
                "rank": min(_rank(label, needle), _rank(key, needle)),
            }
        )
    return items


def _quick(conn, needle: str) -> list[dict]:
    """Favoriten und fehlende Dateien, dieselben Schalter wie im Filterbereich."""
    entries = [
        ("favorite", "Favoriten", "SELECT COUNT(*) AS n FROM clips WHERE favorite = 1 "
                                  "AND status != 'missing'"),
        ("missing", "Fehlende Dateien", "SELECT COUNT(*) AS n FROM clips "
                                        "WHERE status = 'missing'"),
    ]
    items = []
    for value, label, sql in entries:
        if not _matches(label, needle):
            continue
        count = conn.execute(sql).fetchone()["n"]
        if count == 0:
            continue
        items.append(
            {
                "kind": "quick",
                "group": "Schnellzugriff",
                "category": None,
                "value": value,
                "label": label,
                "detail": None,
                "count": count,
                "clip_id": None,
                "rank": _rank(label, needle),
            }
        )
    return items


def _folders(conn, needle: str, raw: str) -> list[dict]:
    rows = conn.execute(
        "SELECT folder, COUNT(*) AS n FROM clips WHERE status != 'missing' "
        "AND folder LIKE ? ESCAPE '\\' GROUP BY folder ORDER BY n DESC LIMIT 12",
        (_like(raw),),
    ).fetchall()
    items = []
    for row in rows:
        name = row["folder"]
        if not name:
            continue
        items.append(
            {
                "kind": "folder",
                "group": "Ordner",
                "category": None,
                "value": name,
                "label": name,
                "detail": None,
                "count": row["n"],
                "clip_id": None,
                "rank": _rank(name, needle),
            }
        )
    return items


def _collections(conn, needle: str) -> list[dict]:
    rows = conn.execute(
        "SELECT c.id, c.name, COUNT(cc.clip_id) AS n FROM collections c "
        "LEFT JOIN collection_clips cc ON cc.collection_id = c.id GROUP BY c.id"
    ).fetchall()
    items = []
    for row in rows:
        if not _matches(row["name"], needle):
            continue
        items.append(
            {
                "kind": "collection",
                "group": "Sammlungen",
                "category": None,
                "value": str(row["id"]),
                "label": row["name"],
                "detail": None,
                "count": row["n"],
                "clip_id": None,
                "rank": _rank(row["name"], needle),
            }
        )
    return items


def _clips(conn, needle: str, raw: str) -> list[dict]:
    pattern = _like(raw)
    rows = conn.execute(
        "SELECT id, filename, folder, duration FROM clips WHERE status != 'missing' "
        "AND (filename LIKE ? ESCAPE '\\' OR original_filename LIKE ? ESCAPE '\\') "
        "ORDER BY COALESCE(recorded_at, created_at) DESC LIMIT 12",
        (pattern, pattern),
    ).fetchall()
    return [
        {
            "kind": "clip",
            "group": "Dateien",
            "category": None,
            "value": row["filename"],
            "label": row["filename"],
            "detail": row["folder"] or None,
            "count": 0,
            "clip_id": row["id"],
            "rank": _rank(row["filename"], needle),
        }
        for row in rows
    ]
