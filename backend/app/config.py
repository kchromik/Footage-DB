"""Zentrale Konfiguration, gelesen aus Umgebungsvariablen mit Präfix FDB_."""

from __future__ import annotations

import functools
import os
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

def default_worker_count() -> int:
    """Voreinstellung für die Worker-Zahl, aus Kernen und Arbeitsspeicher.

    Ein fester Wert ist hier gefährlich: Jeder Worker kann einen
    ffmpeg-Prozess starten, und der belegt bei hochauflösendem Material
    mehrere hundert MB bis über ein GB. Auf einer 8-Kern-NAS mit 7,4 GB RAM
    hat eine zu hohe Zahl den gesamten Arbeitsspeicher aufgebraucht und das
    Gerät ins Swap-Thrashing getrieben. Deshalb ist der Arbeitsspeicher hier
    gleichberechtigt neben der Kernzahl, und nach oben ist bei 4 Schluss.
    """
    cores = os.cpu_count() or 2
    by_cores = max(1, cores // 4)
    try:
        gib = (os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / 1024**3
        by_memory = max(1, int(gib // 3))
    except (AttributeError, OSError, ValueError):
        by_memory = 2
    return max(1, min(4, by_cores, by_memory))


DEFAULT_VIDEO_EXTENSIONS = (
    # insv und 360 sind die Rohformate der 360-Kameras (Insta360, GoPro Max)
    "mp4,mov,m4v,mxf,mts,m2ts,avi,mkv,webm,wmv,mpg,mpeg,braw,r3d,avchd,insv,360"
)

# Ordner, die beim Scan grundsätzlich übersprungen werden
IGNORED_DIRS = {
    "@eaDir",  # Synology Thumbnails
    "#recycle",
    ".Trashes",
    ".Trash",
    "$RECYCLE.BIN",
    "System Volume Information",
    ".fseventsd",
    ".Spotlight-V100",
    ".DocumentRevisions-V100",
    "@Recycle",
    "lost+found",
    ".footagedb",
    ".footagedb-incoming",  # Zwischenablage laufender Uploads
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FDB_",
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Pfade ---------------------------------------------------------
    media_root: Path = Field(
        default=Path("/media"),
        validation_alias=AliasChoices("FDB_MEDIA_ROOT", "FDB_MEDIA_PATH"),
    )
    data_dir: Path = Field(
        default=Path("/data"),
        validation_alias=AliasChoices("FDB_DATA_DIR", "FDB_DATA_PATH"),
    )
    static_dir: Path | None = None

    # --- Login ---------------------------------------------------------
    auth_user: str = "admin"
    auth_password: str = ""
    secret_key: str = ""
    session_max_age: int = 60 * 60 * 24 * 30  # 30 Tage

    # --- Hintergrundarbeit ---------------------------------------------
    worker_count: int = Field(default_factory=lambda: default_worker_count())
    scan_on_start: bool = True
    rescan_interval_minutes: int = 60
    watch_enabled: bool = True

    # --- Vorschauen ----------------------------------------------------
    thumb_width: int = 640
    sprite_frames: int = 20
    sprite_cols: int = 5
    sprite_tile_width: int = 240
    proxy_height: int = 720
    proxy_crf: int = 26
    proxy_audio_bitrate: str = "96k"
    hwaccel: str = "auto"  # auto | vaapi | off
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"
    exiftool_path: str = "exiftool"

    # --- Semantische Suche ---------------------------------------------
    semantic_enabled: bool = True
    semantic_frames: int = 4
    semantic_model: str = "clip-vit-base-patch32"
    # Kleinere, schnellere Modelldateien (int8) auf Kosten etwas schlechterer Treffer
    semantic_quantized: bool = False

    # --- Dateien -------------------------------------------------------
    video_extensions: str = DEFAULT_VIDEO_EXTENSIONS
    organize_uploads: bool = True
    organize_pattern: str = ""
    upload_chunk_size: int = 8 * 1024 * 1024

    # --- Sonstiges -----------------------------------------------------
    log_level: str = "INFO"

    @field_validator("hwaccel")
    @classmethod
    def _norm_hwaccel(cls, value: str) -> str:
        value = (value or "auto").strip().lower()
        return value if value in {"auto", "vaapi", "off"} else "auto"

    @property
    def pattern(self) -> str:
        """Ordnerschema für das Einsortieren, mit Standardwert."""
        return self.organize_pattern.strip() or "{year}/{year}-{month}/{camera}"

    @property
    def extensions(self) -> set[str]:
        return {
            "." + e.strip().lower().lstrip(".")
            for e in self.video_extensions.split(",")
            if e.strip()
        }

    @property
    def db_path(self) -> Path:
        return self.data_dir / "footagedb.sqlite3"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def proxies_dir(self) -> Path:
        return self.data_dir / "proxies"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for path in (
            self.data_dir,
            self.thumbs_dir,
            self.proxies_dir,
            self.models_dir,
            self.uploads_dir,
            self.tmp_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
