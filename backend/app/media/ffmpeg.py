"""Dünne Schicht um ffmpeg, inklusive Erkennung der Hardware-Beschleunigung."""

from __future__ import annotations

import functools
import logging
import os
import subprocess
from pathlib import Path

from ..config import settings
from ..settings_store import runtime

log = logging.getLogger(__name__)

VAAPI_DEVICE = Path("/dev/dri/renderD128")


def thread_limit() -> int:
    """Threads pro ffmpeg-Prozess, abgeleitet aus Kernen und Worker-Zahl.

    Warum das nötig ist: Ohne Begrenzung nimmt sich libx264 alle Kerne und
    legt pro Thread eigene Frame-Puffer an. Bei mehreren Workern parallel
    vervielfacht sich beides. Auf einer 8-Kern-NAS mit 7,4 GB RAM liefen so
    vier Prozesse mit je acht Threads, ein einzelner belegte bei 6K-Material
    1,9 GB. Das Ergebnis war Swap-Thrashing und eine Load von 101, die
    sämtliche anderen Dienste auf dem Gerät unerreichbar gemacht hat.

    Die Obergrenze hält die Summe aller Encoder-Threads bei etwa der Zahl
    der Kerne, unabhängig davon, wie viele Worker eingestellt sind.
    """
    cores = os.cpu_count() or 4
    workers = max(1, runtime.worker_count)
    return max(1, cores // workers)


class FFmpegError(RuntimeError):
    def __init__(self, message: str, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr


def run(args: list[str], timeout: int = 900) -> str:
    """Führt ffmpeg aus und liefert stderr zurück (dort loggt ffmpeg)."""
    try:
        proc = subprocess.run(
            args, capture_output=True, text=True, timeout=timeout, errors="replace"
        )
    except subprocess.TimeoutExpired as exc:
        raise FFmpegError(f"ffmpeg-Zeitlimit nach {timeout}s überschritten") from exc
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()[-6:]
        raise FFmpegError(
            "ffmpeg beendet mit Code " + str(proc.returncode) + ": " + " | ".join(tail),
            proc.stderr or "",
        )
    return proc.stderr or ""


def base_command(*, quiet: bool = True) -> list[str]:
    cmd = [settings.ffmpeg_path, "-hide_banner", "-nostdin", "-y"]
    if quiet:
        cmd += ["-loglevel", "error"]
    # Vor dem -i begrenzt -threads den Dekoder, -filter_threads den
    # Filtergraphen. Die Encoder-Seite braucht die Option als Ausgabeoption
    # und wird deshalb in preview.py separat gesetzt.
    threads = str(thread_limit())
    cmd += ["-threads", threads, "-filter_threads", threads]
    return cmd


@functools.lru_cache(maxsize=1)
def encoders() -> str:
    try:
        proc = subprocess.run(
            [settings.ffmpeg_path, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


@functools.lru_cache(maxsize=1)
def filters() -> str:
    try:
        proc = subprocess.run(
            [settings.ffmpeg_path, "-hide_banner", "-filters"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return proc.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def has_filter(name: str) -> bool:
    return f" {name} " in filters()


@functools.lru_cache(maxsize=1)
def vaapi_available() -> bool:
    """Prüft einmalig, ob VAAPI wirklich nutzbar ist (Gerät + Rechte + Encoder)."""
    if runtime.hwaccel == "off":
        return False
    if not VAAPI_DEVICE.exists():
        if runtime.hwaccel == "vaapi":
            log.warning("VAAPI erzwungen, aber %s fehlt", VAAPI_DEVICE)
        return False
    if "h264_vaapi" not in encoders():
        log.info("ffmpeg kennt keinen h264_vaapi-Encoder")
        return False
    try:
        run(
            base_command()
            + [
                "-vaapi_device", str(VAAPI_DEVICE),
                "-f", "lavfi",
                "-i", "testsrc=size=320x240:rate=1",
                "-frames:v", "2",
                "-vf", "format=nv12,hwupload",
                "-c:v", "h264_vaapi",
                "-f", "null", "-",
            ],
            timeout=30,
        )
    except FFmpegError as exc:
        log.info("VAAPI nicht nutzbar, es wird die CPU verwendet (%s)", exc)
        return False
    log.info("VAAPI aktiv: Hardware-Encoding über %s", VAAPI_DEVICE)
    return True


def describe_acceleration() -> str:
    return "vaapi" if vaapi_available() else "cpu"


def reset_acceleration_cache() -> None:
    """Nach einer Änderung der Einstellung neu prüfen."""
    vaapi_available.cache_clear()


def version(binary: str) -> str | None:
    """Erste Zeile von `-version`, für die Systemprüfung im Assistenten."""
    try:
        proc = subprocess.run(
            [binary, "-version"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    first = (proc.stdout or "").splitlines()
    return first[0].strip() if first else None
