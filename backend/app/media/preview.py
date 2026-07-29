"""Erzeugt Poster, Sprite-Vorschau und Browser-Proxy.

Ablauf pro Clip: Poster direkt aus dem Original (schneller Sprung an eine
Stelle), danach der Proxy als einziger vollstaendiger Durchlauf. Sprite und
CLIP-Frames werden anschliessend aus dem Proxy gezogen, das ist deutlich
guenstiger als noch einmal 4K-Material zu dekodieren.
"""

from __future__ import annotations

import logging
import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..config import settings
from ..settings_store import runtime
from .ffmpeg import FFmpegError, base_command, has_filter, run, vaapi_available

log = logging.getLogger(__name__)

HDR_TRANSFERS = {"smpte2084", "arib-std-b67"}


@dataclass
class SpriteInfo:
    columns: int
    rows: int
    count: int
    tile_width: int
    tile_height: int


def _poster_timestamp(duration: float | None) -> float:
    """Stelle im Clip, die als Vorschaubild dient.

    Der Anfang ist oft schwarz oder verwackelt, deshalb ein Stueck hinein.
    """
    if not duration or duration <= 0:
        return 0.0
    if duration <= 2:
        return duration / 2
    return min(max(duration * 0.12, 1.0), 20.0)


def _tonemap_chain(color_transfer: str | None) -> str | None:
    """Filterkette fuer HDR-Material, damit die Vorschau nicht ausgewaschen wirkt."""
    if color_transfer not in HDR_TRANSFERS or not has_filter("zscale"):
        return None
    return (
        "zscale=t=linear:npl=100,format=gbrpf32le,"
        "zscale=p=bt709,tonemap=tonemap=hable:desat=0,"
        "zscale=t=bt709:m=bt709:r=tv"
    )


# Wie die Projektion beim v360-Filter heisst
V360_INPUT = {
    "equirectangular": "e",
    "half equirectangular": "he",
    "cubemap": "c3x2",
    "eac": "eac",
}


def flatten_chain(
    projection: str | None,
    width: int,
    height: int,
    stereo_mode: str | None = None,
) -> str | None:
    """Rechnet aus einem 360-Panorama einen normalen Bildausschnitt.

    Ohne das zeigt die Kachel die gestreckte Weltkarte, auf der man nichts
    wiedererkennt. Mit rund 100 Grad Blickwinkel sieht sie aus wie eine
    normale Aufnahme. Dual-Fisheye bleibt aussen vor, dafuer braeuchte es
    die Kalibrierung der jeweiligen Kamera.
    """
    mode = V360_INPUT.get(projection or "")
    if not mode or not has_filter("v360"):
        return None
    chain = []
    if stereo_mode == "top-bottom":
        chain.append("crop=iw:ih/2:0:0")
    elif stereo_mode == "left-right":
        chain.append("crop=iw/2:ih:0:0")
    chain.append(f"v360={mode}:flat:h_fov=100:v_fov=70:w={width}:h={height}")
    return ",".join(chain)


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def _scale_filter(target_height: int) -> str:
    # Nie hochskalieren, Breite immer gerade halten (H.264 mag keine ungeraden Werte)
    return f"scale=-2:'min({target_height},ih)'"


def build_poster(
    source: Path,
    destination: Path,
    duration: float | None,
    color_transfer: str | None = None,
    width: int | None = None,
    projection: str | None = None,
    stereo_mode: str | None = None,
) -> None:
    width = width or settings.thumb_width
    timestamp = _poster_timestamp(duration)
    destination.parent.mkdir(parents=True, exist_ok=True)

    flat = flatten_chain(projection, width, _even(width * 9 / 16), stereo_mode)
    filters = [flat] if flat else [f"scale={width}:-2:flags=lanczos"]
    tonemap = _tonemap_chain(color_transfer)
    if tonemap:
        filters.insert(0, tonemap)

    with tempfile.TemporaryDirectory(dir=settings.tmp_dir) as tmp:
        raw = Path(tmp) / "poster.jpg"
        args = base_command()
        if timestamp > 0:
            args += ["-ss", f"{timestamp:.3f}"]
        args += [
            "-i", str(source),
            "-map", "0:v:0",
            "-frames:v", "1",
            "-vf", ",".join(filters),
            "-q:v", "3",
            str(raw),
        ]
        try:
            run(args, timeout=180)
        except FFmpegError:
            if timestamp <= 0:
                raise
            # Manche Dateien lassen sich nicht springen, dann eben von vorn
            args = base_command() + [
                "-i", str(source),
                "-map", "0:v:0",
                "-frames:v", "1",
                "-vf", ",".join(filters),
                "-q:v", "3",
                str(raw),
            ]
            run(args, timeout=300)

        if not raw.exists() or raw.stat().st_size == 0:
            raise FFmpegError("Poster konnte nicht erzeugt werden (leere Ausgabe)")

        with Image.open(raw) as image:
            image = image.convert("RGB")
            _atomic_save(image, destination, quality=80)


def extract_frames(
    source: Path,
    count: int,
    width: int,
    duration: float | None,
    target_dir: Path,
    color_transfer: str | None = None,
    projection: str | None = None,
    stereo_mode: str | None = None,
) -> list[Path]:
    """Zieht count gleichmaessig verteilte Einzelbilder aus dem Video."""
    target_dir.mkdir(parents=True, exist_ok=True)
    count = max(1, count)

    filters: list[str] = []
    tonemap = _tonemap_chain(color_transfer)
    if tonemap:
        filters.append(tonemap)

    if duration and duration > 0.5:
        # Etwas Abstand zu Anfang und Ende, dort ist selten etwas Nuetzliches
        usable = max(duration * 0.9, duration - 0.5)
        offset = (duration - usable) / 2
        rate = count / usable
        filters.append(f"fps={rate:.6f}")
        seek = ["-ss", f"{offset:.3f}"]
    else:
        filters.append("fps=1")
        seek = []

    flat = flatten_chain(projection, width, _even(width * 9 / 16), stereo_mode)
    filters.append(flat if flat else f"scale={width}:-2:flags=bilinear")

    args = base_command() + seek + [
        "-i", str(source),
        "-map", "0:v:0",
        "-vf", ",".join(filters),
        "-frames:v", str(count),
        "-q:v", "4",
        str(target_dir / "frame_%03d.jpg"),
    ]
    run(args, timeout=900)
    return sorted(target_dir.glob("frame_*.jpg"))


def build_sprite(
    source: Path,
    destination: Path,
    duration: float | None,
    color_transfer: str | None = None,
    projection: str | None = None,
    stereo_mode: str | None = None,
) -> SpriteInfo:
    """Kachelblatt fuer die Vorschau beim Drueberfahren im Grid."""
    wanted = settings.sprite_frames
    if duration and duration < 4:
        wanted = max(4, min(wanted, int(duration * 4) or 4))

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.tmp_dir) as tmp:
        frames = extract_frames(
            source,
            wanted,
            settings.sprite_tile_width,
            duration,
            Path(tmp),
            color_transfer,
            projection,
            stereo_mode,
        )
        if not frames:
            raise FFmpegError("Keine Einzelbilder fuer die Vorschau erhalten")

        with Image.open(frames[0]) as first:
            tile_w, tile_h = first.size

        count = len(frames)
        columns = min(settings.sprite_cols, count)
        rows = math.ceil(count / columns)

        sheet = Image.new("RGB", (columns * tile_w, rows * tile_h), (12, 12, 14))
        for index, frame_path in enumerate(frames):
            with Image.open(frame_path) as frame:
                frame = frame.convert("RGB")
                if frame.size != (tile_w, tile_h):
                    frame = frame.resize((tile_w, tile_h), Image.LANCZOS)
                sheet.paste(frame, ((index % columns) * tile_w, (index // columns) * tile_h))

        _atomic_save(sheet, destination, quality=68)
        return SpriteInfo(columns, rows, count, tile_w, tile_h)


def build_proxy(
    source: Path,
    destination: Path,
    has_audio: bool,
    color_transfer: str | None = None,
) -> None:
    """Kleiner H.264-Proxy, damit jedes Format im Browser laeuft."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    tonemap = _tonemap_chain(color_transfer)

    attempts: list[tuple[str, list[str]]] = []
    if vaapi_available() and not tonemap:
        attempts.append(("vaapi", _proxy_args_vaapi(source, destination, has_audio)))
    if tonemap:
        attempts.append(
            ("cpu+tonemap", _proxy_args_cpu(source, destination, has_audio, tonemap))
        )
    attempts.append(("cpu", _proxy_args_cpu(source, destination, has_audio, None)))

    last_error: Exception | None = None
    for label, args in attempts:
        try:
            run(args, timeout=3600)
            if destination.exists() and destination.stat().st_size > 0:
                log.debug("Proxy erzeugt (%s): %s", label, destination.name)
                return
            raise FFmpegError("Proxy ist leer geblieben")
        except FFmpegError as exc:
            last_error = exc
            log.info("Proxy-Versuch '%s' fehlgeschlagen: %s", label, exc)
            destination.unlink(missing_ok=True)
    raise last_error or FFmpegError("Proxy konnte nicht erzeugt werden")


def _audio_args(has_audio: bool) -> list[str]:
    if not has_audio:
        return ["-an"]
    return [
        "-map", "0:a:0?",
        "-c:a", "aac",
        "-b:a", settings.proxy_audio_bitrate,
        "-ac", "2",
    ]


def _proxy_args_cpu(
    source: Path, destination: Path, has_audio: bool, tonemap: str | None
) -> list[str]:
    chain = [_scale_filter(runtime.proxy_height)]
    if tonemap:
        chain.insert(0, tonemap)
    chain.append("format=yuv420p")
    return (
        base_command()
        + [
            "-i", str(source),
            "-map", "0:v:0",
            "-vf", ",".join(chain),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", str(runtime.proxy_crf),
            "-profile:v", "high",
            "-g", "48",
        ]
        + _audio_args(has_audio)
        + ["-sn", "-dn", "-movflags", "+faststart", str(destination)]
    )


def _proxy_args_vaapi(source: Path, destination: Path, has_audio: bool) -> list[str]:
    from .ffmpeg import VAAPI_DEVICE

    return (
        base_command()
        + [
            "-hwaccel", "vaapi",
            "-hwaccel_device", str(VAAPI_DEVICE),
            "-hwaccel_output_format", "vaapi",
            "-i", str(source),
            "-map", "0:v:0",
            "-vf", f"scale_vaapi=w=-2:h='min({runtime.proxy_height},ih)':format=nv12",
            "-c:v", "h264_vaapi",
            "-qp", str(runtime.proxy_crf),
            "-g", "48",
        ]
        + _audio_args(has_audio)
        + ["-sn", "-dn", "-movflags", "+faststart", str(destination)]
    )


def _atomic_save(image: Image.Image, destination: Path, quality: int) -> None:
    """Erst in eine Nebendatei schreiben, dann umbenennen.

    So sieht die Oberflaeche nie ein halb geschriebenes Bild.
    """
    tmp_path = destination.with_suffix(destination.suffix + ".tmp")
    image.save(tmp_path, format="WEBP", quality=quality, method=4)
    shutil.move(str(tmp_path), str(destination))
