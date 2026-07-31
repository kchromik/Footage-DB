"""Die eigentlichen Job-Handler, in der Reihenfolge der Verarbeitungskette.

probe -> poster -> proxy -> sprite -> embed
"""

from __future__ import annotations

import logging
import sqlite3

from . import library, paths
from .config import settings
from .db import get_conn
from .events import bus
from .jobs import handler
from .media import preview
from .metadata.probe import probe_file
from .metadata.rules import derive
from .settings_store import runtime

log = logging.getLogger(__name__)

# Material, das ohnehin jeder Browser abspielt, braucht keinen Proxy
DIRECT_PLAY_CODECS = {"h264"}
DIRECT_PLAY_AUDIO = {"aac", "mp3", None}
DIRECT_PLAY_MAX_HEIGHT = 1080
DIRECT_PLAY_MAX_BITRATE = 14_000_000


def _clip(clip_id: int | None) -> sqlite3.Row | None:
    if clip_id is None:
        return None
    return get_conn().execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()


def _source_for(clip: sqlite3.Row):
    """Quelle für abgeleitete Bilder: bevorzugt der Proxy, sonst das Original."""
    if clip["proxy_status"] == "ready":
        proxy = paths.proxy_path(clip["id"])
        if proxy.exists():
            return proxy, None
    return settings.media_root / clip["path"], clip["color_transfer"]


def _mark_missing(clip_id: int) -> None:
    get_conn().execute(
        "UPDATE clips SET status='missing', updated_at=datetime('now') WHERE id=?",
        (clip_id,),
    )
    bus.publish("clip", id=clip_id, action="missing")


@handler("probe")
def job_probe(job: sqlite3.Row) -> list[tuple[str, int]] | None:
    clip = _clip(job["clip_id"])
    if clip is None:
        return None
    source = settings.media_root / clip["path"]
    if not source.exists():
        _mark_missing(clip["id"])
        return None

    result = probe_file(source, clip["mtime"])
    derived = derive(result, clip["path"], clip["filename"])
    library.apply_probe(clip["id"], result, derived)

    if not result.has_video:
        get_conn().execute(
            "UPDATE clips SET status='error', error=? WHERE id=?",
            ("Keine lesbare Videospur gefunden", clip["id"]),
        )
        return None

    return [("poster", clip["id"]), ("proxy", clip["id"])]


@handler("poster")
def job_poster(job: sqlite3.Row) -> None:
    clip = _clip(job["clip_id"])
    if clip is None:
        return
    source = settings.media_root / clip["path"]
    if not source.exists():
        _mark_missing(clip["id"])
        return

    destination = paths.poster_path(clip["id"])
    preview.build_poster(
        source,
        destination,
        clip["duration"],
        clip["color_transfer"],
        projection=clip["projection"],
        stereo_mode=clip["stereo_mode"],
    )
    get_conn().execute(
        "UPDATE clips SET poster_status='ready', updated_at=datetime('now') WHERE id=?",
        (clip["id"],),
    )
    bus.publish("clip", id=clip["id"], action="poster")


def _can_direct_play(clip: sqlite3.Row) -> bool:
    if clip["video_codec"] not in DIRECT_PLAY_CODECS:
        return False
    if clip["audio_codec"] not in DIRECT_PLAY_AUDIO:
        return False
    if (clip["height"] or 0) > DIRECT_PLAY_MAX_HEIGHT:
        return False
    if (clip["bit_depth"] or 8) > 8:
        return False
    if clip["color_transfer"] in {"smpte2084", "arib-std-b67"}:
        return False
    if (clip["bitrate"] or 0) > DIRECT_PLAY_MAX_BITRATE:
        return False
    container = (clip["container"] or "").lower()
    return "mp4" in container or "mov" in container


@handler("proxy")
def job_proxy(job: sqlite3.Row) -> list[tuple[str, int]] | None:
    clip = _clip(job["clip_id"])
    if clip is None:
        return None
    conn = get_conn()
    follow: list[tuple[str, int]] = [("sprite", clip["id"])]
    if runtime.semantic_enabled:
        follow.append(("embed", clip["id"]))

    if _can_direct_play(clip):
        conn.execute(
            "UPDATE clips SET proxy_status='skipped', updated_at=datetime('now') WHERE id=?",
            (clip["id"],),
        )
        bus.publish("clip", id=clip["id"], action="proxy")
        return follow

    source = settings.media_root / clip["path"]
    if not source.exists():
        _mark_missing(clip["id"])
        return None

    destination = paths.proxy_path(clip["id"])
    preview.build_proxy(
        source,
        destination,
        has_audio=bool(clip["audio_codec"]),
        color_transfer=clip["color_transfer"],
    )
    conn.execute(
        "UPDATE clips SET proxy_status='ready', proxy_size=?, updated_at=datetime('now') "
        "WHERE id=?",
        (destination.stat().st_size, clip["id"]),
    )
    bus.publish("clip", id=clip["id"], action="proxy")
    return follow


@handler("sprite")
def job_sprite(job: sqlite3.Row) -> None:
    clip = _clip(job["clip_id"])
    if clip is None:
        return
    source, transfer = _source_for(clip)
    if not source.exists():
        _mark_missing(clip["id"])
        return

    info = preview.build_sprite(
        source,
        paths.sprite_path(clip["id"]),
        clip["duration"],
        transfer,
        projection=clip["projection"],
        stereo_mode=clip["stereo_mode"],
    )
    get_conn().execute(
        "UPDATE clips SET sprite_status='ready', sprite_cols=?, sprite_rows=?, "
        "sprite_count=?, sprite_tile_w=?, sprite_tile_h=?, updated_at=datetime('now') "
        "WHERE id=?",
        (
            info.columns,
            info.rows,
            info.count,
            info.tile_width,
            info.tile_height,
            clip["id"],
        ),
    )
    bus.publish("clip", id=clip["id"], action="sprite")


@handler("embed")
def job_embed(job: sqlite3.Row) -> None:
    from .search import semantic

    clip = _clip(job["clip_id"])
    if clip is None:
        return
    if not runtime.semantic_enabled:
        get_conn().execute(
            "UPDATE clips SET embed_status='skipped' WHERE id=?", (clip["id"],)
        )
        return

    source, transfer = _source_for(clip)
    if not source.exists():
        _mark_missing(clip["id"])
        return

    semantic.embed_clip(
        clip["id"],
        source,
        clip["duration"],
        transfer,
        projection=clip["projection"],
        stereo_mode=clip["stereo_mode"],
    )
