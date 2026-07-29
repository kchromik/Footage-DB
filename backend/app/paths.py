"""Ablageorte der abgeleiteten Dateien.

Gestaffelt in Unterordner zu je 500 Clips, damit kein Verzeichnis mit
zehntausenden Dateien entsteht (das bremst manche NAS-Dateisysteme aus).
"""

from __future__ import annotations

from pathlib import Path

from .config import settings


def _shard(clip_id: int) -> str:
    return f"{clip_id // 500:04d}"


def poster_path(clip_id: int) -> Path:
    return settings.thumbs_dir / _shard(clip_id) / f"{clip_id}.webp"


def sprite_path(clip_id: int) -> Path:
    return settings.thumbs_dir / _shard(clip_id) / f"{clip_id}_sprite.webp"


def proxy_path(clip_id: int) -> Path:
    return settings.proxies_dir / _shard(clip_id) / f"{clip_id}.mp4"


def artifact_paths(clip_id: int) -> list[Path]:
    return [poster_path(clip_id), sprite_path(clip_id), proxy_path(clip_id)]


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def source_path(rel_path: str) -> Path:
    return settings.media_root / rel_path
