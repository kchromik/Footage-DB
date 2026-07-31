"""Durchsucht den Medienordner und hält die Datenbank aktuell."""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from . import library
from .config import IGNORED_DIRS, settings
from .db import close_conn, get_conn, set_setting
from .events import bus

log = logging.getLogger(__name__)

_scan_lock = threading.Lock()


@dataclass
class ScanResult:
    started_at: float = field(default_factory=time.time)
    files_seen: int = 0
    new: int = 0
    updated: int = 0
    moved: int = 0
    missing: int = 0
    errors: int = 0
    duration: float = 0.0

    def as_dict(self) -> dict:
        return {
            "files_seen": self.files_seen,
            "new": self.new,
            "updated": self.updated,
            "moved": self.moved,
            "missing": self.missing,
            "errors": self.errors,
            "duration": round(self.duration, 1),
        }


def is_hidden(name: str) -> bool:
    return name.startswith(".") or name.startswith("._")


def iter_media_files(root: Path) -> list[tuple[str, os.stat_result]]:
    """Alle Videodateien unterhalb von root, relativ und mit stat-Daten."""
    extensions = settings.extensions
    found: list[tuple[str, os.stat_result]] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames if d not in IGNORED_DIRS and not is_hidden(d)
        ]
        for name in filenames:
            if is_hidden(name):
                continue
            if Path(name).suffix.lower() not in extensions:
                continue
            full = Path(dirpath) / name
            try:
                stat = full.stat()
            except OSError:
                continue
            if stat.st_size == 0:
                continue
            try:
                rel = PurePosixPath(full.relative_to(root)).as_posix()
            except ValueError:
                continue
            found.append((rel, stat))
    return found


def scan(mark_missing: bool = True) -> ScanResult:
    """Vollständiger Durchlauf durch den Medienordner."""
    if not _scan_lock.acquire(blocking=False):
        log.info("Scan läuft bereits, übersprungen")
        return ScanResult()

    result = ScanResult()
    started_iso = _now_iso()
    try:
        root = settings.media_root
        if not root.exists():
            log.error("Medienordner existiert nicht: %s", root)
            bus.publish("scan", state="error", message=f"{root} nicht gefunden")
            return result

        bus.publish("scan", state="start")
        files = iter_media_files(root)
        result.files_seen = len(files)
        log.info("Scan: %d Videodateien gefunden", len(files))

        conn = get_conn()
        for index, (rel, stat) in enumerate(files, start=1):
            try:
                conn.execute("BEGIN IMMEDIATE")
                _, action = library.upsert_scanned_file(rel, stat)
                conn.execute("COMMIT")
                if action == "new":
                    result.new += 1
                elif action == "updated":
                    result.updated += 1
                elif action == "moved":
                    result.moved += 1
            except Exception as exc:  # noqa: BLE001
                try:
                    conn.execute("ROLLBACK")
                except Exception:  # noqa: BLE001
                    pass
                result.errors += 1
                log.exception("Datei konnte nicht aufgenommen werden: %s (%s)", rel, exc)

            if index % 50 == 0 or index == len(files):
                bus.publish(
                    "scan", state="running", done=index, total=len(files)
                )

        if mark_missing:
            cursor = conn.execute(
                "UPDATE clips SET status='missing', updated_at=datetime('now') "
                "WHERE (seen_at IS NULL OR seen_at < ?) AND status != 'missing'",
                (started_iso,),
            )
            result.missing = cursor.rowcount or 0

        set_setting("last_scan_at", _now_iso())
        result.duration = time.time() - result.started_at
        set_setting("last_scan_result", str(result.as_dict()))
        log.info("Scan fertig: %s", result.as_dict())
        bus.publish("scan", state="done", **result.as_dict())
        return result
    finally:
        _scan_lock.release()


def _now_iso() -> str:
    row = get_conn().execute("SELECT datetime('now') AS now").fetchone()
    return row["now"]


def scan_async() -> threading.Thread:
    def runner() -> None:
        try:
            scan()
        finally:
            close_conn()

    thread = threading.Thread(target=runner, name="scan", daemon=True)
    thread.start()
    return thread


def is_scanning() -> bool:
    return _scan_lock.locked()


# --- Dateiüberwachung --------------------------------------------------


class _DebouncedRescan:
    """Sammelt Dateisystem-Ereignisse und startet danach einen Scan.

    Beim Kopieren großer Dateien auf das NAS feuert das Dateisystem viele
    Ereignisse hintereinander. Wir warten deshalb, bis Ruhe eingekehrt ist.
    """

    def __init__(self, delay: float = 20.0) -> None:
        self.delay = delay
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def trigger(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def _fire(self) -> None:
        try:
            scan(mark_missing=True)
        except Exception:  # noqa: BLE001
            log.exception("Automatischer Scan fehlgeschlagen")
        finally:
            close_conn()

    def cancel(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


_observer = None
_debounced = _DebouncedRescan()


def start_watcher() -> None:
    """Beobachtet den Medienordner, fällt bei Netzlaufwerken auf Polling zurück."""
    global _observer
    if not settings.watch_enabled or _observer is not None:
        return
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
        from watchdog.observers.polling import PollingObserver
    except ImportError:
        log.warning("watchdog nicht installiert, Dateiüberwachung deaktiviert")
        return

    extensions = settings.extensions

    class Handler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:
            if event.is_directory:
                return
            path = getattr(event, "dest_path", None) or event.src_path
            name = os.path.basename(path)
            if is_hidden(name):
                return
            if Path(name).suffix.lower() not in extensions:
                return
            _debounced.trigger()

    for observer_cls in (Observer, PollingObserver):
        try:
            observer = observer_cls(timeout=10) if observer_cls is PollingObserver else observer_cls()
            observer.schedule(Handler(), str(settings.media_root), recursive=True)
            observer.start()
            _observer = observer
            log.info("Dateiüberwachung aktiv (%s)", observer_cls.__name__)
            return
        except Exception as exc:  # noqa: BLE001
            log.warning("%s nicht nutzbar: %s", observer_cls.__name__, exc)
    log.warning("Keine Dateiüberwachung möglich, es bleibt beim periodischen Rescan")


def stop_watcher() -> None:
    global _observer
    _debounced.cancel()
    if _observer is not None:
        try:
            _observer.stop()
            _observer.join(timeout=3)
        except Exception:  # noqa: BLE001
            pass
        _observer = None
