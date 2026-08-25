"""Dünne Schicht um ffmpeg, inklusive Erkennung der Hardware-Beschleunigung."""

from __future__ import annotations

import functools
import logging
import os
import subprocess
import tempfile
import threading
from pathlib import Path

from .. import progress
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


def run(
    args: list[str],
    timeout: int = 900,
    *,
    total_seconds: float | None = None,
    total_frames: int | None = None,
) -> str:
    """Führt ffmpeg aus und liefert stderr zurück (dort loggt ffmpeg).

    Ist bekannt, wie lang der Durchlauf wird (Spielzeit oder Zahl der
    Einzelbilder), und läuft der Aufruf innerhalb eines Jobs, dann wird
    ffmpeg über -progress mitgelesen. Nur so kann die Oberfläche zeigen,
    wie weit eine einzelne Datei ist, statt nur dass sie gerade dran ist.
    """
    if (total_seconds or total_frames) and progress.current() is not None:
        return _run_with_progress(args, timeout, total_seconds, total_frames)
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


def _run_with_progress(
    args: list[str],
    timeout: int,
    total_seconds: float | None,
    total_frames: int | None,
) -> str:
    """Wie run(), liest aber nebenbei den Fortschritt aus ffmpeg heraus.

    stderr geht in eine temporäre Datei statt in eine Pipe: Sonst müsste
    nebenher jemand die Pipe leeren, sonst blockiert ffmpeg, sobald der
    Puffer voll ist, und der Job hängt.
    """
    # -progress ist eine globale Option und gehört deshalb vor die Eingabe.
    # -nostats unterdrückt die zweite, unstrukturierte Fortschrittsausgabe.
    command = [args[0], "-progress", "pipe:1", "-nostats", *args[1:]]
    killed = threading.Event()

    with tempfile.TemporaryFile(mode="w+", errors="replace") as errfile:
        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=errfile,
            text=True,
            errors="replace",
        )

        def abbrechen() -> None:
            killed.set()
            try:
                proc.kill()
            except OSError:
                pass  # war in derselben Sekunde ohnehin fertig

        # Ein hängender ffmpeg schreibt nichts mehr, deshalb kann das
        # Zeitlimit nicht in der Leseschleife stecken, sondern braucht
        # einen eigenen Wecker.
        watchdog = threading.Timer(timeout, abbrechen)
        watchdog.start()
        try:
            if proc.stdout is not None:
                for line in proc.stdout:
                    _read_progress_line(line, total_seconds, total_frames)
                proc.stdout.close()
            proc.wait()
        finally:
            watchdog.cancel()

        errfile.seek(0)
        stderr = errfile.read()

    # Erst den Rückgabewert ansehen: Fällt der Wecker genau in dem Moment,
    # in dem ffmpeg fertig wird, war es trotzdem kein Zeitüberschreitung.
    if proc.returncode == 0:
        return stderr
    if killed.is_set():
        raise FFmpegError(f"ffmpeg-Zeitlimit nach {timeout}s überschritten", stderr)
    tail = stderr.strip().splitlines()[-6:]
    raise FFmpegError(
        "ffmpeg beendet mit Code " + str(proc.returncode) + ": " + " | ".join(tail),
        stderr,
    )


def _read_progress_line(
    line: str, total_seconds: float | None, total_frames: int | None
) -> None:
    """Wertet eine Zeile aus `-progress` aus (Format schlüssel=wert)."""
    key, _, value = line.strip().partition("=")
    value = value.strip()
    if not value or value == "N/A":
        return
    try:
        if key == "frame" and total_frames:
            progress.report(fraction=int(value) / max(1, total_frames))
        elif key == "out_time_us" and total_seconds and not total_frames:
            seconds = int(value) / 1_000_000
            progress.report(fraction=seconds / max(0.001, total_seconds))
        elif key == "speed":
            progress.report(speed=float(value.rstrip("x")))
        elif key == "fps":
            progress.report(fps=float(value))
    except ValueError:
        # ffmpeg schreibt hin und wieder Zwischenstände ohne Zahl
        return


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
