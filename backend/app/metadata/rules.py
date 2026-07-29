"""Ableitungen aus den Rohmetadaten: Kameraname, Grading-Status, Auto-Tags.

Alle Heuristiken stehen bewusst in dieser einen Datei, damit sie leicht
nachgeschaerft werden koennen. Ein manuell gesetzter Look gewinnt immer
gegen die Automatik (siehe api/clips.py).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..util import resolution_label
from .probe import ProbeResult

# --- Kameranamen --------------------------------------------------------

# Kryptische Modellbezeichnungen in lesbare Namen uebersetzen
MODEL_ALIASES: dict[str, str] = {
    # Sony
    "ILCE-7SM3": "Sony a7S III",
    "ILCE-7SM2": "Sony a7S II",
    "ILCE-7M4": "Sony a7 IV",
    "ILCE-7M3": "Sony a7 III",
    "ILCE-7RM5": "Sony a7R V",
    "ILCE-7RM4": "Sony a7R IV",
    "ILCE-6700": "Sony a6700",
    "ILCE-6600": "Sony a6600",
    "ILCE-6400": "Sony a6400",
    "ILME-FX3": "Sony FX3",
    "ILME-FX30": "Sony FX30",
    "ILME-FX6": "Sony FX6",
    "ZV-E1": "Sony ZV-E1",
    "ZV-E10": "Sony ZV-E10",
    "ZV-E10M2": "Sony ZV-E10 II",
    "ZV-1": "Sony ZV-1",
    # DJI (Drohnen melden nur ihren Sensorcode)
    "FC3582": "DJI Mini 3 Pro",
    "FC3411": "DJI Air 2S",
    "FC7303": "DJI Mini 2",
    "FC8282": "DJI Mini 4 Pro",
    "FC4170": "DJI Air 3",
    "FC8482": "DJI Mavic 3 Pro",
    "FC3170": "DJI Mavic Air 2",
    "FC220": "DJI Mavic Pro",
}

MAKE_ALIASES = {
    "sony": "Sony",
    "canon": "Canon",
    "nikon": "Nikon",
    "panasonic": "Panasonic",
    "lumix": "Panasonic",
    "apple": "Apple",
    "dji": "DJI",
    "gopro": "GoPro",
    "fujifilm": "Fujifilm",
    "blackmagic": "Blackmagic",
    "blackmagic design": "Blackmagic",
    "insta360": "Insta360",
    "arashi vision": "Insta360",
}

# Wenn gar keine Kamerametadaten vorhanden sind: Rueckschluss aus dem Dateinamen
FILENAME_CAMERA_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^DJI_\d+", re.I), "DJI"),
    (re.compile(r"^(GX|GH|GP|GOPR)\d{6}", re.I), "GoPro"),
    (re.compile(r"^IMG_\d{4}", re.I), "iPhone"),
    (re.compile(r"^C\d{4}\b", re.I), "Sony"),
    (re.compile(r"^MVI_\d{4}", re.I), "Canon"),
    (re.compile(r"^DSC_\d{4}", re.I), "Nikon"),
    (re.compile(r"^P\d{7}", re.I), "Panasonic"),
    (re.compile(r"^IN_?S?\d+", re.I), "Insta360"),
]

# --- Grading-Erkennung --------------------------------------------------

LOG_PROFILE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"s-?log-?3", re.I), "S-Log3"),
    (re.compile(r"s-?log-?2", re.I), "S-Log2"),
    (re.compile(r"c-?log-?3|canon\s*log\s*3", re.I), "C-Log3"),
    (re.compile(r"c-?log-?2|canon\s*log\s*2", re.I), "C-Log2"),
    (re.compile(r"c-?log|canon\s*log", re.I), "C-Log"),
    (re.compile(r"v-?log", re.I), "V-Log"),
    (re.compile(r"d-?log-?m", re.I), "D-Log M"),
    (re.compile(r"d-?log", re.I), "D-Log"),
    (re.compile(r"n-?log", re.I), "N-Log"),
    (re.compile(r"f-?log-?2", re.I), "F-Log2"),
    (re.compile(r"f-?log", re.I), "F-Log"),
    (re.compile(r"gopro\s*flat|protune", re.I), "Flat"),
    (re.compile(r"blackmagic\s*(film|design\s*film)", re.I), "BRAW Film"),
]

EXPORT_SIGNATURES = re.compile(
    r"final\s*cut|fcpx|compressor|premiere|adobe|davinci|resolve|handbrake|"
    r"shutter\s*encoder|lavf|ffmpeg|quicktime\s*player|imovie|capcut|"
    r"screenflow|obs|topaz",
    re.I,
)

PATH_GRADED_HINT = re.compile(
    r"(^|[^a-z])(graded|grading|export|exports|final|master|fertig|renders?|"
    r"published|upload)([^a-z]|$)",
    re.I,
)
# Bewusst eng gehalten: nur Begriffe, die wirklich ein Log-Profil meinen.
# Woerter wie "rushes" oder "original" sagen nur, dass es Rohmaterial ist,
# nicht in welchem Gamma es aufgenommen wurde.
PATH_LOG_HINT = re.compile(
    r"(^|[^a-z])(s-?log-?[23]?|c-?log-?[23]?|v-?log|d-?log|n-?log|f-?log-?2?|"
    r"log|ungraded)([^a-z]|$)",
    re.I,
)

HDR_TRANSFERS = {
    "smpte2084": "PQ",
    "arib-std-b67": "HLG",
}


@dataclass
class Derived:
    camera_label: str | None = None
    look: str = "unknown"
    look_reason: str | None = None
    tags: list[tuple[str, str]] = field(default_factory=list)  # (name, category)

    def add_tag(self, name: str | None, category: str) -> None:
        if not name:
            return
        name = name.strip()
        if name and (name, category) not in self.tags:
            self.tags.append((name, category))


def normalize_camera(make: str | None, model: str | None) -> str | None:
    """Baut aus Hersteller und Modell einen lesbaren Kameranamen."""
    model = (model or "").strip()
    make = (make or "").strip()

    if model:
        alias = MODEL_ALIASES.get(model.upper())
        if alias:
            return alias

    make_clean = MAKE_ALIASES.get(make.lower(), make)
    if make_clean.lower() == "apple" and model.lower().startswith(("iphone", "ipad")):
        make_clean = ""

    if not model:
        return make_clean or None
    if make_clean and model.lower().startswith(make_clean.lower()):
        return model
    if not make_clean:
        return model
    return f"{make_clean} {model}"


def camera_from_filename(filename: str) -> str | None:
    for pattern, label in FILENAME_CAMERA_HINTS:
        if pattern.search(filename):
            return label
    return None


def _profile_from_text(*values: Any) -> str | None:
    haystack = " ".join(str(v) for v in values if v)
    if not haystack:
        return None
    for pattern, label in LOG_PROFILE_PATTERNS:
        if pattern.search(haystack):
            return label
    return None


def detect_look(probe: ProbeResult, rel_path: str) -> tuple[str, str | None, str | None]:
    """Liefert (look, grund, profilname)."""
    exif = probe.raw_tags.get("exif", {}) if probe.raw_tags else {}

    # 1. Ausdrueckliches Kameraprofil in den Metadaten
    profile_sources = [
        exif.get("PhotoStyle"),
        exif.get("PictureProfile"),
        exif.get("ColorMode"),
        exif.get("ProTune"),
        exif.get("GammaCompensation"),
        exif.get("ColorProfile"),
        exif.get("ProfileName"),
        exif.get("PictureMode"),
        exif.get("CaptureGammaEquation"),
        exif.get("CanonLogVersion"),
    ]
    profile = _profile_from_text(*profile_sources)
    if profile:
        return "log", f"Kameraprofil {profile}", profile
    if exif.get("CanonLogVersion"):
        return "log", "Canon Log laut Metadaten", "C-Log"

    # 2. Hinweise aus Ordner- und Dateinamen (deine eigene Ablage schlaegt Raten)
    folder_part = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    if PATH_GRADED_HINT.search(rel_path):
        hint = PATH_GRADED_HINT.search(rel_path).group(2)
        return "graded", f"Pfad enthaelt '{hint}'", None
    if PATH_LOG_HINT.search(folder_part):
        hint = PATH_LOG_HINT.search(folder_part).group(2)
        profile = _profile_from_text(folder_part)
        return "log", f"Ordner enthaelt '{hint}'", profile

    # 3. HDR-Uebertragungsfunktion ist eine harte Tatsache aus der Datei
    if probe.color_transfer in HDR_TRANSFERS:
        return "hdr", f"Transferfunktion {HDR_TRANSFERS[probe.color_transfer]}", None

    # 4. Export-Signatur im Encoder-Feld
    if probe.encoder and EXPORT_SIGNATURES.search(probe.encoder):
        return "graded", f"Encoder '{probe.encoder}'", None
    software = exif.get("Software")
    if software and EXPORT_SIGNATURES.search(str(software)):
        return "graded", f"Software '{software}'", None

    # 5. 10 Bit direkt aus der Kamera spricht stark fuer LOG
    if probe.bit_depth and probe.bit_depth >= 10:
        return "log", "10 Bit ohne Export-Signatur (vermutet)", None

    # 6. Klassisches 8-Bit-Rec.709-Material
    if probe.bit_depth == 8 and probe.color_transfer in {"bt709", None, "unknown"}:
        return "rec709", "8 Bit Rec.709", None

    return "unknown", None, None


def derive(probe: ProbeResult, rel_path: str, filename: str) -> Derived:
    """Erzeugt Kameraname, Look und alle automatischen Tags fuer einen Clip."""
    result = Derived()

    camera = normalize_camera(probe.camera_make, probe.camera_model)
    if not camera:
        camera = camera_from_filename(filename)
    result.camera_label = camera
    result.add_tag(camera, "camera")
    result.add_tag(probe.lens, "lens")

    look, reason, profile = detect_look(probe, rel_path)
    result.look = look
    result.look_reason = reason
    # Der Look selbst steckt in einer eigenen Spalte und ist per Hand
    # ueberschreibbar. Als Tag kommt nur das konkrete Kameraprofil dazu,
    # sonst wuerden Spalte und Tag bei einer Korrektur auseinanderlaufen.
    if look == "log" and profile:
        result.add_tag(profile, "look")

    # Technische Tags
    width, height = probe.width, probe.height
    if probe.rotation in (90, 270) and width and height:
        width, height = height, width
    result.add_tag(resolution_label(width, height), "tech")
    if width and height and height > width:
        result.add_tag("Vertikal", "tech")
    if probe.fps:
        result.add_tag(f"{_round_fps(probe.fps)} fps", "tech")
    if probe.bit_depth and probe.bit_depth >= 10:
        result.add_tag(f"{probe.bit_depth} Bit", "tech")
    if probe.color_transfer in HDR_TRANSFERS:
        result.add_tag(HDR_TRANSFERS[probe.color_transfer], "tech")
    if not probe.audio_codec:
        result.add_tag("Ohne Ton", "tech")
    if probe.gps_lat is not None and probe.gps_lon is not None:
        result.add_tag("GPS", "tech")
    if probe.video_codec:
        result.add_tag(_codec_label(probe.video_codec), "tech")

    # Herkunft
    source = _source_tag(camera, probe, rel_path)
    result.add_tag(source, "source")

    return result


def _round_fps(fps: float) -> str:
    common = [23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 100, 120, 200, 240]
    nearest = min(common, key=lambda c: abs(c - fps))
    if abs(nearest - fps) < 0.5:
        return str(int(round(nearest)))
    return str(int(round(fps)))


_CODEC_LABELS = {
    "h264": "H.264",
    "hevc": "HEVC",
    "prores": "ProRes",
    "dnxhd": "DNxHD",
    "mpeg4": "MPEG-4",
    "mpeg2video": "MPEG-2",
    "vp9": "VP9",
    "av1": "AV1",
    "mjpeg": "MJPEG",
}


def _codec_label(codec: str) -> str:
    return _CODEC_LABELS.get(codec.lower(), codec.upper())


def _source_tag(camera: str | None, probe: ProbeResult, rel_path: str) -> str | None:
    text = f"{camera or ''} {probe.camera_make or ''} {probe.camera_model or ''}"
    if re.search(r"dji|mavic|mini|air\s*\d|inspire", text, re.I) and re.search(
        r"dji", text, re.I
    ):
        return "Drohne"
    if re.search(r"gopro|hero", text, re.I):
        return "Action Cam"
    if re.search(r"iphone|ipad|pixel|galaxy|smartphone", text, re.I):
        return "Smartphone"
    if re.search(r"insta360", text, re.I):
        return "360 Kamera"
    if probe.encoder and EXPORT_SIGNATURES.search(probe.encoder):
        return "Export"
    if camera:
        return "Kamera"
    return None
