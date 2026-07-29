"""FastAPI-Anwendung: API, Hintergrundarbeit und Auslieferung der Oberflaeche."""

from __future__ import annotations

import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import jobs, scanner, tasks  # noqa: F401  (tasks registriert die Job-Handler)
from .config import settings
from .db import close_conn, init_db
from .events import bus
from .api import auth, clips, collections, media, organize, system, tags, uploads

log = logging.getLogger("app")


def configure_logging() -> None:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("watchdog", "httpx", "httpcore", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _preload_semantic() -> None:
    """Modell und Vektorindex im Hintergrund vorbereiten."""
    from .search import semantic
    from .search.clip_model import model

    try:
        semantic.index.load()
    except Exception:  # noqa: BLE001
        log.exception("Vektorindex konnte nicht geladen werden")
    if settings.semantic_enabled:
        try:
            model.ensure_loaded()
        except Exception as exc:  # noqa: BLE001
            log.warning("Inhaltliche Suche steht noch nicht bereit: %s", exc)
    close_conn()


async def _periodic_rescan() -> None:
    interval = max(0, settings.rescan_interval_minutes) * 60
    if interval <= 0:
        return
    while True:
        await asyncio.sleep(interval)
        if scanner.is_scanning():
            continue
        log.info("Periodischer Rescan startet")
        await asyncio.to_thread(_scan_in_thread)


def _scan_in_thread() -> None:
    try:
        scanner.scan()
    except Exception:  # noqa: BLE001
        log.exception("Rescan fehlgeschlagen")
    finally:
        close_conn()


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings.ensure_dirs()
    init_db()
    bus.bind_loop(asyncio.get_running_loop())

    log.info("Medienordner: %s", settings.media_root)
    if not settings.media_root.exists():
        log.error(
            "Der Medienordner %s existiert nicht. Bitte das Volume pruefen.",
            settings.media_root,
        )

    from .api.uploads import cleanup_stale_uploads

    cleaned = cleanup_stale_uploads()
    if cleaned:
        log.info("%d abgebrochene Uploads aufgeraeumt", cleaned)

    jobs.start_pool(settings.worker_count)
    threading.Thread(target=_preload_semantic, name="semantic-preload", daemon=True).start()

    if settings.scan_on_start:
        scanner.scan_async()
    scanner.start_watcher()

    rescan_task = asyncio.create_task(_periodic_rescan())

    try:
        yield
    finally:
        rescan_task.cancel()
        scanner.stop_watcher()
        jobs.stop_pool()
        close_conn()
        log.info("FootageDB beendet")


app = FastAPI(
    title="FootageDB",
    description="B-Roll-Bibliothek fuer das eigene NAS",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.include_router(auth.router)
app.include_router(system.router)
app.include_router(clips.router)
app.include_router(media.router)
app.include_router(tags.router)
app.include_router(uploads.router)
app.include_router(organize.router)
app.include_router(collections.router)


@app.exception_handler(404)
async def not_found(request: Request, exc) -> JSONResponse | FileResponse:
    """API-Pfade liefern JSON, alles andere die Oberflaeche (Client-Routing)."""
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": "Nicht gefunden"}, status_code=404)
    index = _static_dir() / "index.html" if _static_dir() else None
    if index and index.exists():
        return FileResponse(index)
    return JSONResponse({"detail": "Oberflaeche nicht gebaut"}, status_code=404)


def _static_dir() -> Path | None:
    if settings.static_dir:
        return settings.static_dir
    candidate = Path(__file__).resolve().parent.parent / "static"
    return candidate if candidate.exists() else None


_static = _static_dir()
if _static and _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
    log.info("Oberflaeche wird aus %s ausgeliefert", _static)
