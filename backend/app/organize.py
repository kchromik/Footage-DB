"""Dateien nach Jahr/Monat/Kamera einsortieren.

Jeder Umzug laeuft in zwei Schritten: erst ein Plan zum Ansehen, danach die
Ausfuehrung. Jede Bewegung landet in der Tabelle moves und kann als ganzer
Stapel wieder rueckgaengig gemacht werden.
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

from . import library
from .config import settings
from .db import get_conn
from .util import safe_name

log = logging.getLogger(__name__)


@dataclass
class PlannedMove:
    clip_id: int
    from_path: str
    to_path: str
    reason: str = "ok"

    def as_dict(self) -> dict:
        return {
            "clip_id": self.clip_id,
            "from": self.from_path,
            "to": self.to_path,
            "reason": self.reason,
        }


@dataclass
class Plan:
    moves: list[PlannedMove] = field(default_factory=list)
    already_sorted: int = 0
    skipped: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "moves": [move.as_dict() for move in self.moves],
            "already_sorted": self.already_sorted,
            "skipped": self.skipped,
            "count": len(self.moves),
        }


def camera_folder(label: str | None) -> str:
    if not label:
        return "Unbekannte-Kamera"
    return safe_name(label).replace(" ", "-")


def target_directory(recorded_at: str | None, created_at: str, camera: str | None) -> str:
    when = _parse(recorded_at) or _parse(created_at) or datetime.now()
    return settings.pattern.format(
        year=f"{when.year:04d}",
        month=f"{when.month:02d}",
        day=f"{when.day:02d}",
        camera=camera_folder(camera),
    ).strip("/")


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace(" ", "T"))
    except ValueError:
        return None


def unique_target(directory: str, filename: str, taken: set[str]) -> str:
    candidate = f"{directory}/{filename}" if directory else filename
    if candidate not in taken and not (settings.media_root / candidate).exists():
        return candidate
    stem = PurePosixPath(filename).stem
    suffix = PurePosixPath(filename).suffix
    for index in range(2, 1000):
        candidate = (
            f"{directory}/{stem}_{index}{suffix}" if directory else f"{stem}_{index}{suffix}"
        )
        if candidate not in taken and not (settings.media_root / candidate).exists():
            return candidate
    raise RuntimeError("Kein freier Zielname gefunden")


def plan(clip_ids: list[int] | None = None, limit: int | None = None) -> Plan:
    conn = get_conn()
    # Nur fertig eingelesene Clips: solange Aufnahmedatum und Kamera fehlen,
    # wuerde die Datei im falschen Ordner landen.
    if clip_ids:
        placeholders = ",".join("?" * len(clip_ids))
        rows = conn.execute(
            f"SELECT id, path, filename, camera_label, recorded_at, created_at "
            f"FROM clips WHERE status = 'indexed' AND id IN ({placeholders}) ORDER BY id",
            clip_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, path, filename, camera_label, recorded_at, created_at "
            "FROM clips WHERE status = 'indexed' ORDER BY id"
        ).fetchall()

    result = Plan()
    waiting = conn.execute(
        "SELECT COUNT(*) AS n FROM clips WHERE status = 'new'"
    ).fetchone()["n"]
    if waiting:
        result.skipped.append(
            {
                "clip_id": 0,
                "path": "",
                "reason": f"{waiting} Clips werden noch eingelesen und bleiben vorerst liegen",
            }
        )
    taken: set[str] = set()
    for row in rows:
        source = settings.media_root / row["path"]
        if not source.exists():
            result.skipped.append(
                {"clip_id": row["id"], "path": row["path"], "reason": "Datei fehlt"}
            )
            continue

        directory = target_directory(
            row["recorded_at"], row["created_at"], row["camera_label"]
        )
        current_dir = str(PurePosixPath(row["path"]).parent)
        current_dir = "" if current_dir == "." else current_dir
        if current_dir == directory:
            result.already_sorted += 1
            continue

        try:
            target = unique_target(directory, safe_name(row["filename"]), taken)
        except RuntimeError as exc:
            result.skipped.append(
                {"clip_id": row["id"], "path": row["path"], "reason": str(exc)}
            )
            continue

        taken.add(target)
        reason = "ok" if PurePosixPath(target).name == row["filename"] else "umbenannt"
        result.moves.append(PlannedMove(row["id"], row["path"], target, reason))
        if limit and len(result.moves) >= limit:
            break

    return result


def apply(moves: list[PlannedMove]) -> dict:
    """Fuehrt die geplanten Umzuege aus und protokolliert sie."""
    conn = get_conn()
    batch = uuid.uuid4().hex[:12]
    done, failed = 0, 0
    touched_dirs: set[Path] = set()

    for move in moves:
        source = settings.media_root / move.from_path
        destination = settings.media_root / move.to_path
        if not source.exists():
            _log_move(conn, batch, move, "failed", "Quelle fehlt")
            failed += 1
            continue
        if destination.exists():
            _log_move(conn, batch, move, "failed", "Ziel existiert bereits")
            failed += 1
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except OSError as exc:
            _log_move(conn, batch, move, "failed", str(exc))
            failed += 1
            log.warning("Umzug fehlgeschlagen: %s -> %s (%s)", move.from_path, move.to_path, exc)
            continue

        library.update_path(move.clip_id, move.to_path)
        _log_move(conn, batch, move, "done", None)
        touched_dirs.add(source.parent)
        done += 1

    removed = prune_empty_dirs(touched_dirs)
    log.info("Stapel %s: %d verschoben, %d fehlgeschlagen", batch, done, failed)
    return {"batch": batch, "moved": done, "failed": failed, "removed_dirs": removed}


def undo(batch: str) -> dict:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM moves WHERE batch = ? AND state = 'done' ORDER BY id DESC",
        (batch,),
    ).fetchall()
    if not rows:
        return {"reverted": 0, "failed": 0}

    reverted, failed = 0, 0
    touched: set[Path] = set()
    for row in rows:
        source = settings.media_root / row["to_path"]
        destination = settings.media_root / row["from_path"]
        if not source.exists() or destination.exists():
            failed += 1
            continue
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        except OSError as exc:
            log.warning("Ruecknahme fehlgeschlagen: %s", exc)
            failed += 1
            continue
        if row["clip_id"]:
            library.update_path(row["clip_id"], row["from_path"])
        conn.execute("UPDATE moves SET state='reverted' WHERE id=?", (row["id"],))
        touched.add(source.parent)
        reverted += 1

    prune_empty_dirs(touched)
    return {"reverted": reverted, "failed": failed}


def batches(limit: int = 20) -> list[dict]:
    rows = get_conn().execute(
        "SELECT batch, COUNT(*) AS total, "
        "SUM(CASE WHEN state='done' THEN 1 ELSE 0 END) AS done, "
        "SUM(CASE WHEN state='reverted' THEN 1 ELSE 0 END) AS reverted, "
        "MIN(created_at) AS created_at FROM moves "
        "GROUP BY batch ORDER BY MIN(id) DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def prune_empty_dirs(directories: set[Path]) -> int:
    """Entfernt leer gewordene Ordner, aber niemals den Medienordner selbst."""
    root = settings.media_root.resolve()
    removed = 0
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        current = directory.resolve()
        while current != root and root in current.parents:
            try:
                entries = list(current.iterdir())
            except OSError:
                break
            # Systemdateien wie .DS_Store zaehlen nicht als Inhalt
            if any(entry.name not in {".DS_Store", "Thumbs.db"} for entry in entries):
                break
            try:
                for entry in entries:
                    entry.unlink()
                current.rmdir()
                removed += 1
            except OSError:
                break
            current = current.parent
    return removed


def _log_move(conn, batch: str, move: PlannedMove, state: str, error: str | None) -> None:
    conn.execute(
        "INSERT INTO moves(batch, clip_id, from_path, to_path, state, error) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (batch, move.clip_id, move.from_path, move.to_path, state, error),
    )


def target_for_new_file(filename: str, recorded_at: datetime | None, camera: str | None) -> str:
    """Zielpfad fuer eine frisch hochgeladene Datei."""
    when = recorded_at or datetime.now()
    directory = settings.pattern.format(
        year=f"{when.year:04d}",
        month=f"{when.month:02d}",
        day=f"{when.day:02d}",
        camera=camera_folder(camera),
    ).strip("/")
    return unique_target(directory, safe_name(filename), set())
