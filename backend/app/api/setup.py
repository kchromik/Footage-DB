"""Einrichtungsassistent und Einstellungsseite.

Der Assistent laeuft einmalig nach der Installation. Solange noch kein Passwort
gesetzt ist, sind seine Endpunkte offen, sonst kaeme man nicht hinein. Sobald
irgendwo ein Passwort hinterlegt ist (aus der .env oder aus dem Assistenten),
gilt auch hier die normale Anmeldung.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .. import jobs, organize, scanner
from ..config import IGNORED_DIRS, settings
from ..media import ffmpeg
from ..settings_store import runtime
from ..util import human_size
from .deps import current_user, issue_session, require_user

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/setup", tags=["setup"])
settings_router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_user)]
)

SCAN_PREVIEW_LIMIT = 20000
SCAN_PREVIEW_SECONDS = 8.0


def allow_setup(request: Request) -> str:
    """Offen, solange nirgends ein Passwort hinterlegt ist."""
    if runtime.setup_complete or runtime.has_password:
        user = current_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="Nicht angemeldet")
        return user
    return "einrichtung"


# --- Zustand ------------------------------------------------------------


@router.get("/status")
def status(request: Request) -> dict:
    """Wird beim Start der Oberflaeche abgefragt, bewusst ohne Anmeldung."""
    return {
        "complete": runtime.setup_complete,
        "has_password": runtime.has_password,
        "password_from_env": bool(settings.auth_password.strip()),
        "auth_user": runtime.auth_user,
        "logged_in": current_user(request) is not None,
        "media_root": str(settings.media_root),
        "media_exists": settings.media_root.exists(),
    }


# --- Systempruefung -----------------------------------------------------


def _disk(path: Path) -> dict:
    try:
        usage = shutil.disk_usage(path)
        return {
            "free_bytes": usage.free,
            "free_label": human_size(usage.free),
            "total_label": human_size(usage.total),
            "used_percent": round(usage.used / usage.total * 100) if usage.total else 0,
        }
    except OSError:
        return {"free_bytes": 0, "free_label": "unbekannt", "total_label": "unbekannt",
                "used_percent": 0}


def _ownership(path: Path) -> dict:
    """Wem gehoert der Ordner, und als wem laeuft der Container?

    Auf einem NAS ist das die haeufigste Fehlerquelle. Ohne Zugang zur
    Kommandozeile kann man die richtigen Werte fuer PUID und PGID sonst nur
    raten, deshalb zeigt die Pruefung sie direkt an.
    """
    result = {
        "container_uid": os.geteuid(),
        "container_gid": os.getegid(),
        "media_uid": None,
        "media_gid": None,
        "mode": None,
    }
    try:
        info = path.stat()
        result["media_uid"] = info.st_uid
        result["media_gid"] = info.st_gid
        result["mode"] = format(info.st_mode & 0o777, "04o")
    except OSError:
        pass
    result["matches"] = (
        result["media_uid"] in (None, result["container_uid"])
        or result["media_gid"] == result["container_gid"]
    )
    return result


def _writable(path: Path) -> bool:
    probe = path / ".footagedb-schreibtest"
    try:
        probe.write_bytes(b"ok")
        probe.unlink()
        return True
    except OSError:
        return False


@router.get("/check")
def system_check(_: str = Depends(allow_setup)) -> dict:
    media = settings.media_root
    data = settings.data_dir
    warnings: list[str] = []

    media_exists = media.exists()
    media_readable = media_exists and os.access(media, os.R_OK)
    media_writable = media_exists and _writable(media)
    data_writable = data.exists() and _writable(data)
    rechte = _ownership(media)

    if not media_exists:
        warnings.append(
            f"Der Medienordner {media} ist nicht da. Pruef das Volume in der "
            "docker-compose.yml."
        )
    elif not media_readable or not media_writable:
        was = "lesbar" if not media_readable else "beschreibbar"
        hinweis = (
            f"Der Medienordner ist nicht {was}. Er gehoert Benutzer "
            f"{rechte['media_uid']} und Gruppe {rechte['media_gid']} (Modus "
            f"{rechte['mode']}), der Container laeuft als "
            f"{rechte['container_uid']}:{rechte['container_gid']}. "
        )
        if rechte["media_uid"] == 0 and rechte["mode"] in {"0000", "0700", "0750"}:
            # Typisch fuer Freigaben auf NAS-Systemen: die Rechte haengen an
            # ACLs, die klassischen Unix-Bits sind auf null gesetzt
            hinweis += (
                "Das sieht nach einer Freigabe aus, deren Rechte ueber die "
                "Rechteverwaltung deines NAS laufen. Trag dort fuer den Ordner "
                "einen Benutzer mit Schreibrecht ein und setz PUID und PGID auf "
                "dessen IDs. Als Notloesung geht auch PUID=0 und PGID=0, dann "
                "laeuft der Container aber als root und alles was er schreibt "
                "gehoert root."
            )
        else:
            hinweis += (
                f"Setz PUID={rechte['media_uid']} und PGID={rechte['media_gid']} "
                "und starte den Container neu."
            )
        if not media_writable and media_readable:
            hinweis += " Suchen und Herunterladen geht solange trotzdem."
        warnings.append(hinweis)
    if not data_writable:
        warnings.append(
            "Ins Datenverzeichnis kann nicht geschrieben werden. Vorschaubilder und "
            "Previews koennen so nicht entstehen."
        )

    tools = {
        "ffmpeg": ffmpeg.version(settings.ffmpeg_path),
        "ffprobe": ffmpeg.version(settings.ffprobe_path),
        "exiftool": _exiftool_version(),
    }
    if not tools["ffmpeg"] or not tools["ffprobe"]:
        warnings.append("ffmpeg fehlt. Ohne ffmpeg gibt es keine Vorschauen.")
    if not tools["exiftool"]:
        warnings.append(
            "exiftool fehlt. Kamera und Objektiv werden dann nur luecken"
            "haft erkannt."
        )

    vaapi = ffmpeg.vaapi_available()
    media_disk = _disk(media if media_exists else Path("/"))
    data_disk = _disk(data)

    return {
        "media": {
            "path": str(media),
            "exists": media_exists,
            "readable": media_readable,
            "writable": media_writable,
            **media_disk,
        },
        "data": {"path": str(data), "writable": data_writable, **data_disk},
        "permissions": rechte,
        "tools": tools,
        "hwaccel": {
            "available": vaapi,
            "device": str(ffmpeg.VAAPI_DEVICE),
            "device_present": ffmpeg.VAAPI_DEVICE.exists(),
        },
        "cpu_count": os.cpu_count() or 1,
        "internet": _has_internet(),
        "warnings": warnings,
        "ok": media_exists and media_readable and data_writable and bool(tools["ffmpeg"]),
    }


def _exiftool_version() -> str | None:
    try:
        proc = subprocess.run(
            [settings.exiftool_path, "-ver"], capture_output=True, text=True, timeout=15
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return f"ExifTool {proc.stdout.strip()}" if proc.returncode == 0 else None


def _has_internet() -> bool:
    """Nur relevant fuer den einmaligen Download des CLIP-Modells."""
    import socket

    try:
        socket.create_connection(("huggingface.co", 443), timeout=3).close()
        return True
    except OSError:
        return False


# --- Vorschau auf den Medienordner --------------------------------------


@router.get("/preview")
def preview_media(_: str = Depends(allow_setup)) -> dict:
    """Zaehlt, was im Medienordner liegt, ohne die Datenbank anzufassen."""
    root = settings.media_root
    if not root.exists():
        return {"available": False, "count": 0, "bytes": 0, "folders": [], "kinds": {}}

    extensions = settings.extensions
    started = time.time()
    count = 0
    total = 0
    truncated = False
    folders: dict[str, int] = {}
    kinds: dict[str, int] = {}
    newest: float = 0.0
    oldest: float = 0.0

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            if name.startswith("."):
                continue
            suffix = Path(name).suffix.lower()
            if suffix not in extensions:
                continue
            try:
                stat = (Path(dirpath) / name).stat()
            except OSError:
                continue
            count += 1
            total += stat.st_size
            kinds[suffix] = kinds.get(suffix, 0) + 1
            top = Path(dirpath).relative_to(root).parts
            key = top[0] if top else "(Wurzelordner)"
            folders[key] = folders.get(key, 0) + 1
            newest = max(newest, stat.st_mtime)
            oldest = stat.st_mtime if oldest == 0 else min(oldest, stat.st_mtime)

            if count >= SCAN_PREVIEW_LIMIT or time.time() - started > SCAN_PREVIEW_SECONDS:
                truncated = True
                break
        if truncated:
            break

    return {
        "available": True,
        "count": count,
        "truncated": truncated,
        "bytes": total,
        "size_label": human_size(total),
        "folders": sorted(
            ({"name": name, "count": value} for name, value in folders.items()),
            key=lambda entry: -entry["count"],
        )[:12],
        "kinds": kinds,
        "newest": datetime.fromtimestamp(newest).isoformat() if newest else None,
        "oldest": datetime.fromtimestamp(oldest).isoformat() if oldest else None,
        "estimate_minutes": _estimate_minutes(count),
    }


def _estimate_minutes(count: int) -> int:
    """Grobe Hausnummer fuer die erste Verarbeitung.

    Erfahrungswert: mit zwei Workern schafft eine NAS-CPU ungefaehr 15 Clips
    pro Minute, mit Hardware-Encoding deutlich mehr.
    """
    if count <= 0:
        return 0
    per_minute = 40 if ffmpeg.vaapi_available() else 15
    per_minute = per_minute * max(1, runtime.worker_count) / 2
    return max(1, round(count / per_minute))


@router.post("/pattern-preview")
def pattern_preview(payload: dict, _: str = Depends(allow_setup)) -> dict:
    """Zeigt, wie ein Ordnerschema in der Praxis aussieht."""
    pattern = str(payload.get("pattern") or runtime.organize_pattern)
    beispiel = datetime(2026, 7, 14, 16, 30)
    try:
        directory = pattern.format(
            year=f"{beispiel.year:04d}",
            month=f"{beispiel.month:02d}",
            day=f"{beispiel.day:02d}",
            camera=organize.camera_folder("Sony FX3"),
        ).strip("/")
    except (KeyError, IndexError, ValueError) as exc:
        raise HTTPException(
            status_code=400, detail=f"Unbekannter Platzhalter im Schema: {exc}"
        ) from exc
    return {"pattern": pattern, "example": f"{directory}/C0042.MP4"}


# --- Abschluss ----------------------------------------------------------


class SetupPayload(BaseModel):
    auth_user: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=256)
    proxy_height: int = Field(default=720, ge=240, le=2160)
    proxy_crf: int = Field(default=26, ge=14, le=40)
    hwaccel: str = "auto"
    semantic_enabled: bool = True
    worker_count: int = Field(default=2, ge=1, le=16)
    organize_uploads: bool = True
    organize_pattern: str = ""
    rescan_interval_minutes: int = Field(default=60, ge=0, le=1440)
    start_scan: bool = True


ALLOWED_HWACCEL = {"auto", "vaapi", "off"}


@router.post("/complete")
def complete(
    payload: SetupPayload, request: Request, response: Response, _: str = Depends(allow_setup)
) -> dict:
    if payload.hwaccel not in ALLOWED_HWACCEL:
        raise HTTPException(status_code=400, detail="Unbekannte Encoding-Einstellung")

    password_set = False
    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(
                status_code=400, detail="Das Passwort braucht mindestens 8 Zeichen"
            )
        runtime.set_password(payload.password)
        password_set = True
    elif not runtime.has_password:
        log.warning("Einrichtung ohne Passwort abgeschlossen")

    values = {
        "proxy_height": payload.proxy_height,
        "proxy_crf": payload.proxy_crf,
        "hwaccel": payload.hwaccel,
        "semantic_enabled": payload.semantic_enabled,
        "worker_count": payload.worker_count,
        "organize_uploads": payload.organize_uploads,
        "rescan_interval_minutes": payload.rescan_interval_minutes,
    }
    if payload.auth_user.strip():
        values["auth_user"] = payload.auth_user.strip()
    if payload.organize_pattern.strip():
        values["organize_pattern"] = payload.organize_pattern.strip()

    runtime.set_many(values)
    _apply_runtime_changes(worker_count=payload.worker_count)
    runtime.mark_setup_complete()
    log.info("Einrichtung abgeschlossen")

    # Wurde gerade erst ein Passwort gesetzt, gaebe es sonst keine gueltige
    # Sitzung und der Assistent wuerde direkt in den Anmeldebildschirm kippen.
    if password_set:
        secure = request.url.scheme == "https" or (
            request.headers.get("x-forwarded-proto") == "https"
        )
        issue_session(response, runtime.auth_user, secure=secure)

    started = False
    if payload.start_scan and settings.media_root.exists() and not scanner.is_scanning():
        scanner.scan_async()
        started = True

    return {"complete": True, "scan_started": started}


def _apply_runtime_changes(worker_count: int | None = None) -> None:
    ffmpeg.reset_acceleration_cache()
    if worker_count is not None and jobs.pool is not None and jobs.pool.count != worker_count:
        log.info("Worker-Anzahl wird auf %d gesetzt", worker_count)
        jobs.stop_pool()
        jobs.start_pool(worker_count)


# --- Einstellungen spaeter aendern --------------------------------------


class SettingsPayload(BaseModel):
    auth_user: str | None = None
    password: str | None = None
    proxy_height: int | None = Field(default=None, ge=240, le=2160)
    proxy_crf: int | None = Field(default=None, ge=14, le=40)
    hwaccel: str | None = None
    semantic_enabled: bool | None = None
    worker_count: int | None = Field(default=None, ge=1, le=16)
    organize_uploads: bool | None = None
    organize_pattern: str | None = None
    rescan_interval_minutes: int | None = Field(default=None, ge=0, le=1440)


@settings_router.get("")
def read_settings() -> dict:
    return {
        "auth_user": runtime.auth_user,
        "has_password": runtime.has_password,
        "password_from_env": bool(settings.auth_password.strip()),
        "proxy_height": runtime.proxy_height,
        "proxy_crf": runtime.proxy_crf,
        "hwaccel": runtime.hwaccel,
        "hwaccel_active": ffmpeg.describe_acceleration(),
        "semantic_enabled": runtime.semantic_enabled,
        "worker_count": runtime.worker_count,
        "organize_uploads": runtime.organize_uploads,
        "organize_pattern": runtime.organize_pattern,
        "rescan_interval_minutes": runtime.rescan_interval_minutes,
        "media_root": str(settings.media_root),
        "restart_hint": "Die Anzahl der Worker wird sofort uebernommen.",
    }


@settings_router.patch("")
def update_settings(payload: SettingsPayload) -> dict:
    values: dict = {}
    for key in (
        "proxy_height",
        "proxy_crf",
        "semantic_enabled",
        "worker_count",
        "organize_uploads",
        "rescan_interval_minutes",
    ):
        value = getattr(payload, key)
        if value is not None:
            values[key] = value

    if payload.hwaccel is not None:
        if payload.hwaccel not in ALLOWED_HWACCEL:
            raise HTTPException(status_code=400, detail="Unbekannte Encoding-Einstellung")
        values["hwaccel"] = payload.hwaccel
    if payload.auth_user is not None and payload.auth_user.strip():
        values["auth_user"] = payload.auth_user.strip()
    if payload.organize_pattern is not None and payload.organize_pattern.strip():
        values["organize_pattern"] = payload.organize_pattern.strip()

    if payload.password:
        if len(payload.password) < 8:
            raise HTTPException(
                status_code=400, detail="Das Passwort braucht mindestens 8 Zeichen"
            )
        runtime.set_password(payload.password)

    if values:
        runtime.set_many(values)
    _apply_runtime_changes(worker_count=values.get("worker_count"))
    return read_settings()
