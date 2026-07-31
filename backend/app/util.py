"""Kleine Hilfsfunktionen ohne Abhängigkeit zum Rest der App."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

import xxhash

HASH_CHUNK = 1024 * 1024  # 1 MB vom Anfang und vom Ende


def content_hash(path: Path, size: int | None = None) -> str:
    """Schnelle Datei-Identität.

    Liest Anfang und Ende der Datei plus die Größe. Das reicht, um eine
    verschobene oder umbenannte Datei sicher wiederzuerkennen, ohne mehrere
    Gigabyte durch die Prüfsumme zu schicken.
    """
    if size is None:
        size = path.stat().st_size
    digest = xxhash.xxh3_128()
    digest.update(str(size).encode())
    with path.open("rb") as handle:
        digest.update(handle.read(HASH_CHUNK))
        if size > HASH_CHUNK * 2:
            handle.seek(-HASH_CHUNK, 2)
            digest.update(handle.read(HASH_CHUNK))
    return digest.hexdigest()


def slugify(value: str, fallback: str = "unbekannt") -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = value.encode("ascii", "ignore").decode("ascii")
    value = re.sub(r"[^0-9A-Za-z]+", "-", value).strip("-").lower()
    return value or fallback


def safe_name(value: str, fallback: str = "unbenannt") -> str:
    """Dateiname ohne Pfadanteile und ohne Zeichen, die Dateisysteme ärgern."""
    value = (value or "").replace("\\", "/").split("/")[-1]
    value = value.replace("\x00", "")
    value = re.sub(r'[<>:"|?*\x00-\x1f]', "_", value).strip(" .")
    return value or fallback


def safe_join(root: Path, relative: str) -> Path:
    """Verhindert Ausbrüche aus dem Medienordner (../.. und Konsorten)."""
    candidate = (root / relative).resolve()
    root_resolved = root.resolve()
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(f"Pfad liegt außerhalb des Medienordners: {relative}")
    return candidate


def rel_posix(path: Path, root: Path) -> str:
    return PurePosixPath(path.relative_to(root)).as_posix()


def parse_datetime(value: str | None) -> datetime | None:
    """Versteht die gängigen Zeitformate aus ffprobe und exiftool."""
    if not value:
        return None
    text = str(value).strip()
    if not text or text.startswith("0000"):
        return None

    # exiftool: 2026:07:14 18:22:31+02:00
    match = re.match(
        r"^(\d{4})[:\-](\d{2})[:\-](\d{2})[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?"
        r"\s*(Z|[+\-]\d{2}:?\d{2})?$",
        text,
    )
    if match:
        year, month, day, hour, minute, second, tz = match.groups()
        try:
            dt = datetime(
                int(year), int(month), int(day), int(hour), int(minute), int(second)
            )
        except ValueError:
            return None
        if tz and tz != "Z":
            sign = 1 if tz[0] == "+" else -1
            tz_clean = tz[1:].replace(":", "")
            offset = int(tz_clean[:2]) * 60 + int(tz_clean[2:4])
            from datetime import timedelta

            dt = dt.replace(tzinfo=timezone(sign * timedelta(minutes=offset)))
        elif tz == "Z":
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


FILENAME_DATE_PATTERNS = [
    re.compile(r"(?P<y>20\d{2})[-_]?(?P<m>[01]\d)[-_]?(?P<d>[0-3]\d)[-_ T]"
               r"(?P<H>[0-2]\d)[-_:]?(?P<M>[0-5]\d)[-_:]?(?P<S>[0-5]\d)"),
    re.compile(r"(?P<y>20\d{2})[-_]?(?P<m>[01]\d)[-_]?(?P<d>[0-3]\d)"),
]


def date_from_filename(name: str) -> datetime | None:
    """Letzte Rettung: Datum aus dem Dateinamen ziehen (GoPro, DJI, Screenrec)."""
    for pattern in FILENAME_DATE_PATTERNS:
        match = pattern.search(name)
        if not match:
            continue
        groups = match.groupdict()
        try:
            return datetime(
                int(groups["y"]),
                int(groups["m"]),
                int(groups["d"]),
                int(groups.get("H") or 0),
                int(groups.get("M") or 0),
                int(groups.get("S") or 0),
            )
        except (ValueError, TypeError):
            continue
    return None


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0).isoformat()


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024 or unit == "TB":
            return f"{num:.1f} {unit}" if unit != "B" else f"{int(num)} B"
        num /= 1024
    return f"{num:.1f} TB"


def resolution_label(width: int | None, height: int | None) -> str | None:
    """Kurzlabel für die Auflösung, an der längeren Kante orientiert."""
    if not width or not height:
        return None
    long_edge = max(width, height)
    if long_edge >= 7000:
        return "8K"
    if long_edge >= 5000:
        return "6K"
    if long_edge >= 3400:
        return "4K"
    if long_edge >= 2000:
        return "2.7K"
    if long_edge >= 1800:
        return "1080p"
    if long_edge >= 1200:
        return "720p"
    return "SD"


def format_duration(seconds: float | None) -> str:
    if not seconds or seconds < 0:
        return "0:00"
    total = int(round(seconds))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"
