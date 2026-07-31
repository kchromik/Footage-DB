"""Metadaten aus Videodateien lesen.

Dreistufig, weil keine Quelle allein alles liefert:
1. ffprobe  für die technischen Daten (Codec, Auflösung, Dauer, Farbraum)
2. exiftool für Kamera, Objektiv, Aufnahmedatum und GPS
3. Sony-XML-Sidecar, falls vorhanden
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import settings
from ..util import date_from_filename, parse_datetime

log = logging.getLogger(__name__)

FFPROBE_TIMEOUT = 120
EXIFTOOL_TIMEOUT = 60

# Gezielte Tag-Auswahl: deutlich schneller als der komplette exiftool-Dump
EXIFTOOL_TAGS = [
    "Make", "Model", "CameraModelName", "DeviceManufacturer", "DeviceModelName",
    "LensModel", "LensID", "LensType", "LensSpec", "LensInfo",
    "CreateDate", "DateTimeOriginal", "MediaCreateDate", "TrackCreateDate",
    "SubSecDateTimeOriginal", "CreationDate", "ContentCreateDate",
    "GPSLatitude", "GPSLongitude", "GPSAltitude",
    "Software", "Encoder", "CompressorName", "HandlerDescription",
    "MajorBrand", "ContentIdentifier", "Title", "Comment", "Description",
    "PhotoStyle", "PictureProfile", "CanonLogVersion", "ColorMode", "ProTune",
    "GammaCompensation", "PictureMode", "ColorProfile", "ProfileName",
    "Rotation", "AndroidVersion", "XMLData",
    # 360-Material (Google Spatial Media, XMP-GSpherical)
    "ProjectionType", "Spherical", "Stitched", "StitchingSoftware",
    "SourceCount", "StereoMode", "FullPanoWidthPixels", "InitialViewHeadingDegrees",
]

# Projektionen, wie ffprobe und exiftool sie benennen, auf einen kurzen
# Bezeichner gebracht
PROJECTIONS = {
    "equirectangular": "equirectangular",
    "half equirectangular": "half equirectangular",
    "tiled equirectangular": "equirectangular",
    "cubemap": "cubemap",
    "equi-angular cubemap": "eac",
    "eac": "eac",
}


@dataclass
class ProbeResult:
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    audio_channels: int | None = None
    pix_fmt: str | None = None
    bit_depth: int | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    color_space: str | None = None
    bitrate: int | None = None
    rotation: int = 0
    container: str | None = None
    encoder: str | None = None
    projection: str | None = None
    stereo_mode: str | None = None

    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    recorded_at: datetime | None = None
    recorded_source: str | None = None
    gps_lat: float | None = None
    gps_lon: float | None = None

    raw_tags: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def has_video(self) -> bool:
        return bool(self.width and self.height)

    @property
    def is_spherical(self) -> bool:
        return bool(self.projection)


def _run(cmd: list[str], timeout: int) -> tuple[int, str, str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        errors="replace",
    )
    return proc.returncode, proc.stdout, proc.stderr


def _fraction(value: str | None) -> float | None:
    if not value or "/" not in str(value):
        try:
            return float(value) if value else None
        except (TypeError, ValueError):
            return None
    num, _, den = str(value).partition("/")
    try:
        numerator, denominator = float(num), float(den)
    except ValueError:
        return None
    if denominator == 0:
        return None
    return numerator / denominator


def _int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bit_depth(stream: dict[str, Any]) -> int | None:
    depth = _int(stream.get("bits_per_raw_sample"))
    if depth:
        return depth
    pix_fmt = str(stream.get("pix_fmt") or "")
    for candidate in (16, 14, 12, 10):
        if str(candidate) in pix_fmt:
            return candidate
    return 8 if pix_fmt else None


def run_ffprobe(path: Path) -> dict[str, Any] | None:
    code, out, err = _run(
        [
            settings.ffprobe_path,
            "-v", "error",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        FFPROBE_TIMEOUT,
    )
    if code != 0:
        log.warning("ffprobe fehlgeschlagen für %s: %s", path.name, err.strip()[:400])
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        log.warning("ffprobe lieferte kein gültiges JSON für %s", path.name)
        return None


def run_exiftool(path: Path) -> dict[str, Any]:
    args = [settings.exiftool_path, "-j", "-n", "-api", "largefilesupport=1"]
    args += [f"-{tag}" for tag in EXIFTOOL_TAGS]
    args.append(str(path))
    try:
        code, out, err = _run(args, EXIFTOOL_TIMEOUT)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.debug("exiftool nicht verfügbar oder zu langsam: %s", exc)
        return {}
    if code != 0 and not out.strip():
        log.debug("exiftool fehlgeschlagen für %s: %s", path.name, err.strip()[:200])
        return {}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, list) and data:
        return {k: v for k, v in data[0].items() if v not in (None, "")}
    return {}


def read_sony_sidecar(path: Path) -> dict[str, Any]:
    """Sony legt neben C0001.MP4 eine C0001M01.XML mit Kameradaten ab."""
    candidates = [
        path.with_name(path.stem + "M01.XML"),
        path.with_name(path.stem + "M01.xml"),
        path.with_suffix(".XML"),
        path.with_suffix(".xml"),
    ]
    for candidate in candidates:
        if not candidate.exists() or candidate.stat().st_size > 2_000_000:
            continue
        try:
            root = ET.parse(candidate).getroot()
        except (ET.ParseError, OSError):
            continue
        result: dict[str, Any] = {}
        for element in root.iter():
            tag = element.tag.rsplit("}", 1)[-1]
            if tag == "Device":
                if element.get("manufacturer"):
                    result["Make"] = element.get("manufacturer")
                if element.get("modelName"):
                    result["Model"] = element.get("modelName")
            elif tag == "CreationDate" and element.get("value"):
                result["CreationDate"] = element.get("value")
            elif tag == "Lens":
                if element.get("modelName"):
                    result["LensModel"] = element.get("modelName")
            elif tag == "VideoFrame":
                if element.get("captureFps"):
                    result["CaptureFps"] = element.get("captureFps")
            elif tag == "Item" and element.get("name") in {
                "CaptureGammaEquation",
                "CaptureColorPrimaries",
                "CaptureGammaOffset",
            }:
                result[element.get("name")] = element.get("value")
        if result:
            result["_sidecar"] = candidate.name
            return result
    return {}


_DATE_TAGS = (
    "SubSecDateTimeOriginal",
    "DateTimeOriginal",
    "CreationDate",
    "CreateDate",
    "MediaCreateDate",
    "ContentCreateDate",
    "TrackCreateDate",
)


def _pick_recorded_at(
    exif: dict[str, Any],
    ffprobe_tags: dict[str, Any],
    path: Path,
    mtime: float,
) -> tuple[datetime | None, str]:
    for tag in _DATE_TAGS:
        parsed = parse_datetime(exif.get(tag))
        # 1904 ist der QuickTime-Nullwert, taucht bei manchen Exporten auf
        if parsed and parsed.year > 1970:
            return parsed, f"exif:{tag}"

    for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
        parsed = parse_datetime(ffprobe_tags.get(key))
        if parsed and parsed.year > 1970:
            return parsed, f"ffprobe:{key}"

    from_name = date_from_filename(path.name)
    if from_name:
        return from_name, "filename"

    return datetime.fromtimestamp(mtime), "mtime"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"unknown", "n/a", "none", "0"}:
        return None
    return re.sub(r"\s+", " ", text)


def probe_file(path: Path, mtime: float | None = None) -> ProbeResult:
    """Liest alle verfügbaren Metadaten einer Datei zusammen."""
    result = ProbeResult()
    if mtime is None:
        mtime = path.stat().st_mtime

    data = run_ffprobe(path)
    ffprobe_tags: dict[str, Any] = {}
    if data:
        fmt = data.get("format") or {}
        ffprobe_tags = {k.lower(): v for k, v in (fmt.get("tags") or {}).items()}
        result.duration = _float(fmt.get("duration"))
        result.bitrate = _int(fmt.get("bit_rate"))
        # ffprobe liefert eine Liste wie "mov,mp4,m4a,3gp,3g2,mj2", davon
        # reicht der erste Eintrag
        container = _clean(fmt.get("format_name"))
        result.container = container.split(",")[0] if container else None
        result.encoder = _clean(ffprobe_tags.get("encoder"))

        video = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "video"
             and s.get("disposition", {}).get("attached_pic", 0) != 1),
            None,
        )
        audio = next(
            (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
            None,
        )
        if video:
            result.width = _int(video.get("width"))
            result.height = _int(video.get("height"))
            result.fps = _fraction(video.get("r_frame_rate")) or _fraction(
                video.get("avg_frame_rate")
            )
            result.video_codec = _clean(video.get("codec_name"))
            result.pix_fmt = _clean(video.get("pix_fmt"))
            result.bit_depth = _bit_depth(video)
            result.color_transfer = _clean(video.get("color_transfer"))
            result.color_primaries = _clean(video.get("color_primaries"))
            result.color_space = _clean(video.get("color_space"))
            if result.duration is None:
                result.duration = _float(video.get("duration"))
            stream_tags = {k.lower(): v for k, v in (video.get("tags") or {}).items()}
            ffprobe_tags.update(stream_tags)
            result.rotation = _rotation(video, stream_tags)
        if audio:
            result.audio_codec = _clean(audio.get("codec_name"))
            result.audio_channels = _int(audio.get("channels"))
    else:
        result.warnings.append("ffprobe konnte die Datei nicht lesen")

    exif = run_exiftool(path)
    sidecar = read_sony_sidecar(path)
    if sidecar:
        for key, value in sidecar.items():
            exif.setdefault(key, value)

    result.camera_make = _clean(exif.get("Make") or exif.get("DeviceManufacturer")
                                or ffprobe_tags.get("com.apple.quicktime.make"))
    result.camera_model = _clean(
        exif.get("Model")
        or exif.get("CameraModelName")
        or exif.get("DeviceModelName")
        or ffprobe_tags.get("com.apple.quicktime.model")
    )
    result.lens = _clean(
        exif.get("LensModel") or exif.get("LensID") or exif.get("LensType")
    )
    result.gps_lat = _float(exif.get("GPSLatitude"))
    result.gps_lon = _float(exif.get("GPSLongitude"))
    if not result.encoder:
        result.encoder = _clean(
            exif.get("Software") or exif.get("Encoder") or exif.get("CompressorName")
        )

    recorded_at, source = _pick_recorded_at(exif, ffprobe_tags, path, mtime)
    result.recorded_at = recorded_at
    result.recorded_source = source

    result.projection, result.stereo_mode = detect_spherical(
        video if data else None, exif, path, result.width, result.height
    )

    result.raw_tags = {
        "exif": exif,
        "ffprobe": ffprobe_tags,
    }
    return result


def detect_spherical(
    video: dict[str, Any] | None,
    exif: dict[str, Any],
    path: Path,
    width: int | None,
    height: int | None,
) -> tuple[str | None, str | None]:
    """Erkennt 360-Material und seine Projektion.

    Drei Quellen, in dieser Reihenfolge: die sv3d-Box, die ffprobe als
    Seitendaten meldet, die XMP-Angaben von Google Spatial Media, die
    exiftool liest, und zuletzt das Seitenverhältnis. Ein Vollpanorama ist
    immer exakt 2:1, das kommt sonst praktisch nicht vor.
    """
    projection: str | None = None
    stereo: str | None = None

    for side_data in (video or {}).get("side_data_list") or []:
        kind = str(side_data.get("side_data_type", "")).lower()
        if "spherical" in kind:
            raw = str(side_data.get("projection", "equirectangular")).lower()
            projection = PROJECTIONS.get(raw, raw)
        elif "stereo 3d" in kind:
            stereo = _stereo_label(side_data.get("type"))

    if not projection:
        raw = _clean(exif.get("ProjectionType"))
        if raw:
            projection = PROJECTIONS.get(raw.lower(), raw.lower())
        elif str(exif.get("Spherical", "")).lower() in {"true", "1", "yes"}:
            projection = "equirectangular"

    if not stereo:
        stereo = _stereo_label(exif.get("StereoMode"))

    suffix = path.suffix.lower()
    if not projection and suffix == ".360":
        # GoPro Max legt zwei Spuren in einer eigenen Variante des
        # Würfelformats ab, ohne die übliche Metadatenbox
        projection = "eac"
    if not projection and suffix == ".insv":
        projection = "dualfisheye"

    if not projection and width and height:
        if width == height * 2 and width >= 2880:
            projection = "equirectangular"

    return projection, stereo


def _stereo_label(value: Any) -> str | None:
    text = str(value or "").lower().replace("_", "-").replace(" ", "-")
    if not text or text in {"mono", "monoscopic", "none", "0"}:
        return None
    if "top" in text or "tb" in text or "over-under" in text:
        return "top-bottom"
    if "side" in text or "left-right" in text or "lr" in text:
        return "left-right"
    return None


def _rotation(video: dict[str, Any], stream_tags: dict[str, Any]) -> int:
    for side_data in video.get("side_data_list") or []:
        rotation = side_data.get("rotation")
        if rotation is not None:
            try:
                return int(round(float(rotation))) % 360
            except (TypeError, ValueError):
                pass
    raw = stream_tags.get("rotate")
    try:
        return int(float(raw)) % 360 if raw is not None else 0
    except (TypeError, ValueError):
        return 0
