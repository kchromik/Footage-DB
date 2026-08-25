"""Was gerade in Arbeit ist, live aus den laufenden ffmpeg-Prozessen.

Warum das nicht in SQLite landet: Der Fortschritt eines Proxys ändert sich
mehrmals pro Sekunde und ist nach einem Neustart wertlos. Jede Änderung zu
schreiben würde die Datenbank ausbremsen, ohne dass jemand etwas davon hat.
Der Zustand lebt deshalb im Speicher, genau wie der Worker, zu dem er gehört.

Die Zuordnung läuft über ein threading.local: Der Worker meldet mit begin()
an, welchen Job er übernommen hat, und tief unten in ffmpeg.run() genügt
dann report(), ohne den Eintrag durch jede Funktion durchreichen zu müssen.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field

from .events import bus

log = logging.getLogger(__name__)

# Wie oft der Fortschritt höchstens in die Oberfläche geschoben wird.
# Alles darunter sieht niemand, kostet aber Ereignisse.
PUBLISH_INTERVAL = 0.8

LABELS = {
    "probe": "Metadaten lesen",
    "poster": "Vorschaubild",
    "proxy": "Vorschau berechnen",
    "sprite": "Vorschaustreifen",
    "embed": "Bildanalyse",
}


@dataclass
class ActiveJob:
    """Ein Job, der gerade auf einem Worker läuft."""

    job_id: int
    type: str
    clip_id: int | None = None
    filename: str = ""
    folder: str = ""
    duration: float | None = None
    size_bytes: int = 0
    stage: str = ""
    fraction: float | None = None
    speed: float | None = None
    fps: float | None = None
    started_at: float = field(default_factory=time.time)

    def as_dict(self) -> dict:
        elapsed = max(0.0, time.time() - self.started_at)
        eta: float | None = None
        # Unter einem Prozent ist die Hochrechnung reines Rauschen
        if self.fraction is not None and 0.01 < self.fraction < 1.0:
            eta = elapsed * (1.0 - self.fraction) / self.fraction
        return {
            "job_id": self.job_id,
            "type": self.type,
            "label": LABELS.get(self.type, self.type),
            "clip_id": self.clip_id,
            "filename": self.filename,
            "folder": self.folder,
            "duration": self.duration,
            "size_bytes": self.size_bytes,
            "stage": self.stage,
            "fraction": self.fraction,
            "speed": self.speed,
            "fps": self.fps,
            "elapsed": round(elapsed, 1),
            "eta": round(eta, 1) if eta is not None else None,
        }


_lock = threading.Lock()
_active: dict[int, ActiveJob] = {}
_local = threading.local()
_last_publish = 0.0


def begin(
    job_id: int,
    job_type: str,
    clip_id: int | None = None,
    filename: str = "",
    folder: str = "",
    duration: float | None = None,
    size_bytes: int = 0,
) -> ActiveJob:
    entry = ActiveJob(
        job_id=job_id,
        type=job_type,
        clip_id=clip_id,
        filename=filename,
        folder=folder,
        duration=duration,
        size_bytes=size_bytes,
    )
    with _lock:
        _active[job_id] = entry
    _local.entry = entry
    publish(force=True)
    return entry


def finish(job_id: int) -> None:
    with _lock:
        _active.pop(job_id, None)
    _local.entry = None
    publish(force=True)


def current() -> ActiveJob | None:
    return getattr(_local, "entry", None)


def stage(text: str) -> None:
    """Setzt die Kurzbeschreibung dessen, was gerade passiert."""
    entry = current()
    if entry is None:
        return
    entry.stage = text
    entry.fraction = None
    entry.speed = None
    entry.fps = None
    publish(force=True)


def report(
    fraction: float | None = None,
    speed: float | None = None,
    fps: float | None = None,
) -> None:
    """Meldet Fortschritt des laufenden Unterprozesses, gedrosselt."""
    entry = current()
    if entry is None:
        return
    if fraction is not None:
        # Erst der beendete Prozess darf 100 Prozent anzeigen
        entry.fraction = min(0.999, max(0.0, fraction))
    if speed is not None:
        entry.speed = speed
    if fps is not None:
        entry.fps = fps
    publish()


def snapshot() -> list[dict]:
    with _lock:
        entries = sorted(_active.values(), key=lambda item: item.started_at)
    return [entry.as_dict() for entry in entries]


def publish(force: bool = False) -> None:
    global _last_publish
    now = time.monotonic()
    if not force and now - _last_publish < PUBLISH_INTERVAL:
        return
    _last_publish = now
    try:
        bus.publish("progress", items=snapshot())
    except Exception:  # noqa: BLE001 - Anzeige darf nie einen Job kippen
        log.debug("Fortschritt konnte nicht veröffentlicht werden", exc_info=True)


def reset() -> None:
    """Nur für Tests und den Neustart des Worker-Pools."""
    with _lock:
        _active.clear()
    _local.entry = None
