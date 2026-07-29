"""Testumgebung: eigene Ordner und Einstellungen, bevor die App importiert wird."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="footagedb-test-"))
os.environ.update(
    {
        "FDB_MEDIA_ROOT": str(_TMP / "media"),
        "FDB_DATA_DIR": str(_TMP / "data"),
        "FDB_AUTH_USER": "tester",
        "FDB_AUTH_PASSWORD": "geheim",
        "FDB_SECRET_KEY": "test-schluessel",
        "FDB_SEMANTIC_ENABLED": "false",
        "FDB_SCAN_ON_START": "false",
        "FDB_WATCH_ENABLED": "false",
        "FDB_RESCAN_INTERVAL_MINUTES": "0",
        "FDB_WORKER_COUNT": "1",
        "FDB_LOG_LEVEL": "WARNING",
    }
)
(_TMP / "media").mkdir(parents=True, exist_ok=True)
(_TMP / "data").mkdir(parents=True, exist_ok=True)

from app.config import settings  # noqa: E402
from app.db import close_conn, get_conn, init_db  # noqa: E402

HAS_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg nicht installiert")


@pytest.fixture(autouse=True)
def clean_database():
    """Vor jedem Test eine leere Datenbank."""
    close_conn()
    if settings.db_path.exists():
        settings.db_path.unlink()
        for suffix in ("-wal", "-shm"):
            Path(str(settings.db_path) + suffix).unlink(missing_ok=True)
    settings.ensure_dirs()
    init_db()
    yield
    close_conn()


@pytest.fixture
def media_root():
    root = settings.media_root
    for entry in root.iterdir():
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    return root


def make_clip(
    path: Path,
    seconds: float = 1.0,
    size: str = "320x180",
    fps: int = 25,
    audio: bool = False,
    extra: list[str] | None = None,
) -> Path:
    """Erzeugt eine kleine echte Videodatei fuer die Tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={fps}:duration={seconds}",
    ]
    if audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    args += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "34"]
    args += extra or []
    args.append(str(path))
    subprocess.run(args, check=True, capture_output=True)
    return path


@pytest.fixture
def conn():
    return get_conn()
