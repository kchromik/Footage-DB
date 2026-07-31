"""Tests für Kameraerkennung, Grading-Heuristik und automatische Tags."""

from __future__ import annotations

import pytest

from app.metadata.probe import ProbeResult
from app.metadata.rules import camera_from_filename, derive, detect_look, normalize_camera


def probe(**kwargs) -> ProbeResult:
    defaults = dict(
        width=1920,
        height=1080,
        fps=25.0,
        duration=10.0,
        video_codec="h264",
        bit_depth=8,
        color_transfer="bt709",
        raw_tags={"exif": {}, "ffprobe": {}},
    )
    defaults.update(kwargs)
    return ProbeResult(**defaults)


class TestNormalizeCamera:
    @pytest.mark.parametrize(
        "make,model,expected",
        [
            ("Sony", "ILME-FX3", "Sony FX3"),
            ("SONY", "ILCE-7SM3", "Sony a7S III"),
            ("Apple", "iPhone 15 Pro", "iPhone 15 Pro"),
            ("Canon", "Canon EOS R5", "Canon EOS R5"),
            ("DJI", "FC3582", "DJI Mini 3 Pro"),
            ("Panasonic", "DC-GH6", "Panasonic DC-GH6"),
            (None, "HERO12 Black", "HERO12 Black"),
            ("GoPro", None, "GoPro"),
            (None, None, None),
        ],
    )
    def test_namen(self, make, model, expected):
        assert normalize_camera(make, model) == expected

    def test_verdoppelt_den_hersteller_nicht(self):
        assert normalize_camera("Canon", "Canon EOS R6") == "Canon EOS R6"


class TestCameraFromFilename:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("DJI_0042.MP4", "DJI"),
            ("GX010023.MP4", "GoPro"),
            ("IMG_4711.MOV", "iPhone"),
            ("C0001.MP4", "Sony"),
            ("MVI_1234.MOV", "Canon"),
            ("beliebig.mp4", None),
        ],
    )
    def test_erkennung(self, name, expected):
        assert camera_from_filename(name) == expected


class TestDetectLook:
    def test_kameraprofil_gewinnt(self):
        result = probe(raw_tags={"exif": {"PhotoStyle": "V-Log"}, "ffprobe": {}})
        look, reason, profile = detect_look(result, "Rushes/P1000123.MOV")
        assert look == "log"
        assert profile == "V-Log"
        assert "V-Log" in reason

    def test_slog3_aus_sony_sidecar(self):
        result = probe(
            bit_depth=10,
            raw_tags={"exif": {"CaptureGammaEquation": "s-log3-cine"}, "ffprobe": {}},
        )
        look, _, profile = detect_look(result, "C0001.MP4")
        assert look == "log"
        assert profile == "S-Log3"

    def test_pfad_hinweis_graded(self):
        look, reason, _ = detect_look(probe(), "Export/Video_final.mp4")
        assert look == "graded"
        assert "Export" in reason

    def test_pfad_hinweis_log(self):
        look, _, _ = detect_look(probe(bit_depth=10), "2026/SLOG/A001.MP4")
        assert look == "log"

    def test_rushes_ist_kein_log_hinweis(self):
        # "Rushes" sagt nur Rohmaterial, nichts über das Gamma
        look, reason, _ = detect_look(probe(bit_depth=8), "Rushes/A001.MP4")
        assert look == "rec709"

    def test_hlg_wird_als_hdr_erkannt(self):
        look, reason, _ = detect_look(probe(color_transfer="arib-std-b67", bit_depth=10), "a.mov")
        assert look == "hdr"
        assert "HLG" in reason

    def test_pq_wird_als_hdr_erkannt(self):
        look, _, _ = detect_look(probe(color_transfer="smpte2084", bit_depth=10), "a.mov")
        assert look == "hdr"

    def test_export_signatur(self):
        look, reason, _ = detect_look(probe(encoder="Apple Final Cut Pro 11.0"), "a.mp4")
        assert look == "graded"
        assert "Final Cut" in reason

    def test_zehn_bit_gilt_als_log(self):
        look, reason, _ = detect_look(probe(bit_depth=10, color_transfer=None), "A001.MP4")
        assert look == "log"
        assert "10 Bit" in reason

    def test_acht_bit_rec709(self):
        look, _, _ = detect_look(probe(bit_depth=8), "A001.MP4")
        assert look == "rec709"


class TestDerive:
    def test_technische_tags(self):
        result = derive(
            probe(width=3840, height=2160, fps=59.94, bit_depth=10, audio_codec=None),
            "Rushes/A001.MP4",
            "A001.MP4",
        )
        names = {name for name, _ in result.tags}
        assert "4K" in names
        assert "60 fps" in names
        assert "10 Bit" in names
        assert "Ohne Ton" in names
        assert "H.264" in names

    def test_vertikal_wird_erkannt(self):
        result = derive(probe(width=1080, height=1920), "a.mov", "a.mov")
        assert ("Vertikal", "tech") in result.tags

    def test_rotation_dreht_die_aufloesung(self):
        result = derive(probe(width=1920, height=1080, rotation=90), "a.mov", "a.mov")
        assert ("Vertikal", "tech") in result.tags

    def test_kamera_und_herkunft(self):
        result = derive(
            probe(camera_make="DJI", camera_model="FC3582"),
            "Drohne/DJI_0001.MP4",
            "DJI_0001.MP4",
        )
        assert result.camera_label == "DJI Mini 3 Pro"
        assert ("Drohne", "source") in result.tags

    def test_kein_generisches_look_tag(self):
        # Der Look steckt in einer eigenen Spalte, nur das konkrete
        # Kameraprofil wird zusätzlich als Tag geführt
        result = derive(probe(bit_depth=10), "a.mp4", "a.mp4")
        assert result.look == "log"
        assert not [name for name, category in result.tags if category == "look"]

    def test_profil_wird_zum_tag(self):
        result = derive(
            probe(raw_tags={"exif": {"PhotoStyle": "V-Log"}, "ffprobe": {}}),
            "a.mp4",
            "a.mp4",
        )
        assert ("V-Log", "look") in result.tags

    def test_gps_tag(self):
        result = derive(probe(gps_lat=52.5, gps_lon=13.4), "a.mp4", "a.mp4")
        assert ("GPS", "tech") in result.tags
