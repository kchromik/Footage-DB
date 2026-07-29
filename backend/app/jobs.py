"""Hintergrund-Jobs.

Die Warteschlange liegt in SQLite, die Worker sind einfache Threads. Das
reicht voellig fuer eine Ein-Container-App und spart Redis und Celery.
Die eigentliche Arbeit passiert ohnehin in ffmpeg-Unterprozessen.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from collections.abc import Callable
from typing import Any

from .db import close_conn, get_conn, transaction
from .events import bus

log = logging.getLogger(__name__)

# type -> (handler, standard-prioritaet)
_HANDLERS: dict[str, tuple[Callable[[sqlite3.Row], Any], int]] = {}

PRIORITIES = {"probe": 10, "poster": 20, "sprite": 30, "proxy": 40, "embed": 50}
MAX_ATTEMPTS = 3


def handler(job_type: str, priority: int = 100):
    def decorator(func: Callable[[sqlite3.Row], Any]):
        _HANDLERS[job_type] = (func, PRIORITIES.get(job_type, priority))
        return func

    return decorator


def enqueue(
    job_type: str,
    clip_id: int | None = None,
    payload: str | None = None,
    priority: int | None = None,
    conn: sqlite3.Connection | None = None,
) -> None:
    """Legt einen Job an. Doppelte offene Jobs werden vom Index verhindert."""
    conn = conn or get_conn()
    if priority is None:
        priority = PRIORITIES.get(job_type, 100)
    conn.execute(
        "INSERT OR IGNORE INTO jobs(type, clip_id, payload, priority) VALUES (?, ?, ?, ?)",
        (job_type, clip_id, payload, priority),
    )
    _wake.set()


def enqueue_many(job_type: str, clip_ids: list[int]) -> None:
    if not clip_ids:
        return
    priority = PRIORITIES.get(job_type, 100)
    conn = get_conn()
    conn.executemany(
        "INSERT OR IGNORE INTO jobs(type, clip_id, priority) VALUES (?, ?, ?)",
        [(job_type, cid, priority) for cid in clip_ids],
    )
    _wake.set()


def queue_stats() -> dict[str, int]:
    rows = get_conn().execute(
        "SELECT state, COUNT(*) AS n FROM jobs "
        "WHERE state IN ('queued','running') GROUP BY state"
    ).fetchall()
    stats = {row["state"]: row["n"] for row in rows}
    return {
        "queued": stats.get("queued", 0),
        "running": stats.get("running", 0),
        "failed": get_conn().execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE state='failed'"
        ).fetchone()["n"],
    }


_wake = threading.Event()


def _claim_job() -> sqlite3.Row | None:
    """Holt den naechsten Job und markiert ihn als laufend."""
    try:
        with transaction() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE state='queued' ORDER BY priority, id LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE jobs SET state='running', started_at=datetime('now'), "
                "attempts=attempts+1 WHERE id=?",
                (row["id"],),
            )
            return row
    except sqlite3.OperationalError as exc:
        log.warning("Konnte keinen Job holen: %s", exc)
        time.sleep(0.5)
        return None


class WorkerPool:
    def __init__(self, count: int) -> None:
        self.count = max(1, count)
        self._threads: list[threading.Thread] = []
        self._stop = threading.Event()
        self.active: dict[int, str] = {}
        self._lock = threading.Lock()
        self._last_event = 0.0

    def start(self) -> None:
        for index in range(self.count):
            thread = threading.Thread(
                target=self._loop, name=f"worker-{index}", daemon=True
            )
            thread.start()
            self._threads.append(thread)
        log.info("%d Worker gestartet", self.count)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        _wake.set()
        for thread in self._threads:
            thread.join(timeout=timeout)
        self._threads.clear()

    def _loop(self) -> None:
        idle_since = 0.0
        while not self._stop.is_set():
            job = _claim_job()
            if job is None:
                if idle_since == 0.0:
                    idle_since = time.time()
                _wake.wait(timeout=2.0)
                _wake.clear()
                continue
            idle_since = 0.0
            self._run_job(job)
        close_conn()

    def _run_job(self, job: sqlite3.Row) -> None:
        entry = _HANDLERS.get(job["type"])
        conn = get_conn()
        if entry is None:
            conn.execute(
                "UPDATE jobs SET state='failed', error=?, finished_at=datetime('now') "
                "WHERE id=?",
                (f"Unbekannter Job-Typ {job['type']}", job["id"]),
            )
            return

        func, _ = entry
        with self._lock:
            self.active[job["id"]] = f"{job['type']}:{job['clip_id']}"
        self._emit()
        try:
            follow_ups = func(job)
            conn.execute(
                "UPDATE jobs SET state='done', error=NULL, finished_at=datetime('now') "
                "WHERE id=?",
                (job["id"],),
            )
            for item in follow_ups or []:
                if isinstance(item, tuple):
                    enqueue(item[0], item[1])
                else:
                    enqueue(item, job["clip_id"])
        except Exception as exc:  # noqa: BLE001 - Worker darf nie sterben
            message = f"{type(exc).__name__}: {exc}"
            log.exception("Job %s (%s) fehlgeschlagen", job["id"], job["type"])
            state = "queued" if job["attempts"] < MAX_ATTEMPTS else "failed"
            conn.execute(
                "UPDATE jobs SET state=?, error=?, finished_at=datetime('now') WHERE id=?",
                (state, message[:2000], job["id"]),
            )
            if state == "failed" and job["clip_id"]:
                _mark_clip_failure(conn, job["type"], job["clip_id"], message)
        finally:
            with self._lock:
                self.active.pop(job["id"], None)
            self._emit(force=True)

    def _emit(self, force: bool = False) -> None:
        now = time.time()
        if not force and now - self._last_event < 0.5:
            return
        self._last_event = now
        try:
            bus.publish("queue", **queue_stats())
        except Exception:  # noqa: BLE001
            pass


def _mark_clip_failure(
    conn: sqlite3.Connection, job_type: str, clip_id: int, message: str
) -> None:
    column = {
        "poster": "poster_status",
        "sprite": "sprite_status",
        "proxy": "proxy_status",
        "embed": "embed_status",
    }.get(job_type)
    if column:
        conn.execute(f"UPDATE clips SET {column}='failed' WHERE id=?", (clip_id,))
    elif job_type == "probe":
        conn.execute(
            "UPDATE clips SET status='error', error=? WHERE id=?", (message[:500], clip_id)
        )


pool: WorkerPool | None = None


def start_pool(count: int) -> WorkerPool:
    global pool
    pool = WorkerPool(count)
    pool.start()
    return pool


def stop_pool() -> None:
    global pool
    if pool is not None:
        pool.stop()
        pool = None


def retry_failed() -> int:
    conn = get_conn()
    cursor = conn.execute(
        "UPDATE jobs SET state='queued', attempts=0, error=NULL WHERE state='failed'"
    )
    _wake.set()
    return cursor.rowcount
