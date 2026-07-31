"""Tests für die Hilfsfunktionen: Datumsformate, Namen, Pfade, Prüfsummen."""

from __future__ import annotations

from datetime import datetime

import pytest

from app.util import (
    content_hash,
    date_from_filename,
    format_duration,
    human_size,
    parse_datetime,
    resolution_label,
    safe_join,
    safe_name,
    slugify,
)


class TestParseDatetime:
    def test_exiftool_format(self):
        assert parse_datetime("2026:07:14 18:22:31") == datetime(2026, 7, 14, 18, 22, 31)

    def test_mit_zeitzone(self):
        parsed = parse_datetime("2026:07:14 18:22:31+02:00")
        assert parsed is not None
        assert parsed.hour == 18
        assert parsed.utcoffset() is not None

    def test_ffprobe_iso(self):
        parsed = parse_datetime("2026-05-14T10:22:31.000000Z")
        assert parsed is not None
        assert parsed.year == 2026 and parsed.month == 5

    def test_quicktime_nullwert(self):
        # QuickTime nutzt 1904 als "kein Datum"
        assert parse_datetime("0000:00:00 00:00:00") is None

    @pytest.mark.parametrize("value", ["", None, "irgendwas"])
    def test_unbrauchbar(self, value):
        assert parse_datetime(value) is None


class TestDateFromFilename:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("2026-07-14_12-30-05_clip.mp4", datetime(2026, 7, 14, 12, 30, 5)),
            ("VID_20260714_123005.mp4", datetime(2026, 7, 14, 12, 30, 5)),
            ("Aufnahme 2026-07-14.mov", datetime(2026, 7, 14)),
        ],
    )
    def test_erkennt_datum(self, name, expected):
        assert date_from_filename(name) == expected

    def test_ohne_datum(self):
        assert date_from_filename("C0001.MP4") is None

    def test_ignoriert_unsinnige_werte(self):
        assert date_from_filename("2026-99-99.mp4") is None


class TestSafeName:
    def test_entfernt_pfadanteile(self):
        assert safe_name("../../etc/passwd.mp4") == "passwd.mp4"

    def test_ersetzt_verbotene_zeichen(self):
        assert safe_name('a:b*c?.mp4') == "a_b_c_.mp4"

    def test_leerer_name_bekommt_ersatz(self):
        assert safe_name("   ") == "unbenannt"


class TestSafeJoin:
    def test_erlaubt_unterordner(self, media_root):
        (media_root / "a" / "b").mkdir(parents=True)
        # safe_join löst Symlinks auf (auf macOS zeigt /var nach /private/var),
        # deshalb wird gegen den aufgelösten Wurzelpfad geprüft
        assert safe_join(media_root, "a/b").is_relative_to(media_root.resolve())

    def test_blockiert_ausbruch(self, media_root):
        with pytest.raises(ValueError):
            safe_join(media_root, "../../../etc")


class TestContentHash:
    def test_gleiche_datei_gleicher_hash(self, media_root):
        first = media_root / "a.bin"
        second = media_root / "b.bin"
        payload = b"x" * 5000
        first.write_bytes(payload)
        second.write_bytes(payload)
        assert content_hash(first) == content_hash(second)

    def test_andere_groesse_anderer_hash(self, media_root):
        first = media_root / "a.bin"
        second = media_root / "b.bin"
        first.write_bytes(b"x" * 5000)
        second.write_bytes(b"x" * 5001)
        assert content_hash(first) != content_hash(second)

    def test_grosse_datei_nutzt_anfang_und_ende(self, media_root):
        size = 3 * 1024 * 1024
        first = media_root / "a.bin"
        second = media_root / "b.bin"
        first.write_bytes(b"A" + b"0" * (size - 2) + b"Z")
        second.write_bytes(b"A" + b"0" * (size - 2) + b"Y")
        assert content_hash(first) != content_hash(second)


@pytest.mark.parametrize(
    "width,height,expected",
    [
        (3840, 2160, "4K"),
        (4096, 2160, "4K"),
        (1920, 1080, "1080p"),
        (1080, 1920, "1080p"),  # hochkant zählt die lange Kante
        (1280, 720, "720p"),
        (7680, 4320, "8K"),
        (None, None, None),
    ],
)
def test_resolution_label(width, height, expected):
    assert resolution_label(width, height) == expected


@pytest.mark.parametrize(
    "seconds,expected",
    [(0, "0:00"), (5, "0:05"), (65, "1:05"), (3661, "1:01:01"), (None, "0:00")],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_human_size():
    assert human_size(512) == "512 B"
    assert human_size(1536) == "1.5 KB"
    assert human_size(5 * 1024**3) == "5.0 GB"


def test_slugify():
    assert slugify("Sony FX3") == "sony-fx3"
    assert slugify("Grün & Blau") == "grun-blau"
    assert slugify("") == "unbekannt"
