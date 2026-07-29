"""Umwandlung der Datenbankzeilen in das JSON-Format der Oberflaeche."""

from __future__ import annotations

import sqlite3
import zlib

from .db import get_conn
from .util import format_duration, human_size, resolution_label


def load_tags(clip_ids: list[int]) -> dict[int, list[dict]]:
    if not clip_ids:
        return {}
    placeholders = ",".join("?" * len(clip_ids))
    rows = get_conn().execute(
        f"SELECT ct.clip_id AS clip_id, t.name AS name, t.category AS category, "
        f"ct.source AS source FROM clip_tags ct JOIN tags t ON t.id = ct.tag_id "
        f"WHERE ct.clip_id IN ({placeholders}) ORDER BY t.category, t.name",
        clip_ids,
    ).fetchall()
    result: dict[int, list[dict]] = {}
    for row in rows:
        result.setdefault(row["clip_id"], []).append(
            {"name": row["name"], "category": row["category"], "source": row["source"]}
        )
    return result


def _version(row: sqlite3.Row) -> str:
    return format(zlib.crc32((row["updated_at"] or "").encode()) & 0xFFFF, "x")


def serialize_clip(
    row: sqlite3.Row, tags: list[dict] | None = None, score: float | None = None
) -> dict:
    width, height = row["width"], row["height"]
    if row["rotation"] in (90, 270) and width and height:
        width, height = height, width

    version = _version(row)
    clip_id = row["id"]
    look = row["look_manual"] or row["look"] or "unknown"

    data = {
        "id": clip_id,
        "path": row["path"],
        "filename": row["filename"],
        "original_filename": row["original_filename"],
        "folder": row["folder"],
        "ext": row["ext"],
        "status": row["status"],
        "error": row["error"],
        "size_bytes": row["size_bytes"],
        "size_label": human_size(row["size_bytes"] or 0),
        "duration": row["duration"],
        "duration_label": format_duration(row["duration"]),
        "width": width,
        "height": height,
        "resolution": resolution_label(width, height),
        "fps": round(row["fps"], 3) if row["fps"] else None,
        "video_codec": row["video_codec"],
        "audio_codec": row["audio_codec"],
        "audio_channels": row["audio_channels"],
        "bit_depth": row["bit_depth"],
        "pix_fmt": row["pix_fmt"],
        "color_transfer": row["color_transfer"],
        "color_primaries": row["color_primaries"],
        "bitrate": row["bitrate"],
        "container": row["container"],
        "encoder": row["encoder"],
        "rotation": row["rotation"],
        "camera": row["camera_label"],
        "camera_make": row["camera_make"],
        "camera_model": row["camera_model"],
        "lens": row["lens"],
        "recorded_at": row["recorded_at"],
        "recorded_source": row["recorded_source"],
        "gps": (
            {"lat": row["gps_lat"], "lon": row["gps_lon"]}
            if row["gps_lat"] is not None and row["gps_lon"] is not None
            else None
        ),
        "look": look,
        "look_auto": row["look"],
        "look_manual": row["look_manual"],
        "look_reason": row["look_reason"],
        "title": row["title"],
        "notes": row["notes"],
        "favorite": bool(row["favorite"]),
        "rating": row["rating"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "poster_status": row["poster_status"],
        "proxy_status": row["proxy_status"],
        "sprite_status": row["sprite_status"],
        "embed_status": row["embed_status"],
        "poster_url": (
            f"/api/media/{clip_id}/poster?v={version}"
            if row["poster_status"] == "ready"
            else None
        ),
        "play_url": f"/api/media/{clip_id}/play",
        "download_url": f"/api/media/{clip_id}/download",
        "playable": row["proxy_status"] in ("ready", "skipped"),
        "tags": tags if tags is not None else [],
    }

    if row["sprite_status"] == "ready" and row["sprite_count"]:
        data["sprite"] = {
            "url": f"/api/media/{clip_id}/sprite?v={version}",
            "columns": row["sprite_cols"],
            "rows": row["sprite_rows"],
            "count": row["sprite_count"],
            "tile_width": row["sprite_tile_w"],
            "tile_height": row["sprite_tile_h"],
        }
    else:
        data["sprite"] = None

    if score is not None:
        data["score"] = round(score, 4)
    return data
