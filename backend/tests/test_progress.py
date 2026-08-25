"""Tests für die Fortschrittsanzeige.

Zwei Dinge müssen stimmen: Der Worker muss melden, woran er sitzt, und
ffmpeg muss unterwegs Zahlen liefern. Ohne das zweite steht in der
Oberfläche nur "wird bearbeitet", und genau das war der Anlass.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import jobs, progress
from app.config import settings
from app.media import ffmpeg
from conftest import needs_ffmpeg
from helpers import insert_clip


@pytest.fixture(autouse=True)
def sauberer_zustand():
    progress.reset()
    yield
    progress.reset()


class TestEintraege:
    def test_begin_und_finish(self):
        progress.begin(1, "proxy", 7, filename="a.mp4", duration=12.0)
        eintrag = progress.snapshot()[0]
        assert eintrag["type"] == "proxy"
        assert eintrag["label"] == "Vorschau berechnen"
        assert eintrag["filename"] == "a.mp4"
        assert eintrag["clip_id"] == 7

        progress.finish(1)
        assert progress.snapshot() == []

    def test_report_ohne_laufenden_job_ist_folgenlos(self):
        # Ein ffmpeg-Aufruf aus dem Assistenten heraus hat keinen Job
        progress.report(fraction=0.5)
        assert progress.snapshot() == []

    def test_fortschritt_und_hochrechnung(self):
        eintrag = progress.begin(2, "proxy", 7, filename="a.mp4", duration=100.0)
        eintrag.started_at = time.time() - 10
        progress.report(fraction=0.5, speed=2.5, fps=48.0)

        daten = progress.snapshot()[0]
        assert daten["fraction"] == 0.5
        assert daten["speed"] == 2.5
        assert daten["fps"] == 48.0
        # Halbe Strecke in 10 Sekunden, also noch einmal ungefähr 10
        assert 9 <= daten["eta"] <= 11

    def test_fortschritt_bleibt_unter_hundert_prozent(self):
        progress.begin(3, "proxy")
        progress.report(fraction=1.4)
        assert progress.snapshot()[0]["fraction"] == 0.999

    def test_stufe_setzt_den_fortschritt_zurueck(self):
        # Jeder Abschnitt zählt von vorn, sonst springt der Balken zurück
        # und wirkt kaputt.
        progress.begin(4, "sprite")
        progress.report(fraction=0.8)
        progress.stage("Kachelblatt zusammensetzen")

        daten = progress.snapshot()[0]
        assert daten["stage"] == "Kachelblatt zusammensetzen"
        assert daten["fraction"] is None


class TestZeilenAuswertung:
    def setup_method(self):
        progress.reset()
        progress.begin(9, "proxy", duration=60.0)

    def test_spielzeit(self):
        ffmpeg._read_progress_line("out_time_us=30000000\n", 60.0, None)
        assert progress.snapshot()[0]["fraction"] == 0.5

    def test_einzelbilder_haben_vorrang(self):
        # Beim Sprite verschiebt der fps-Filter die Zeitachse, dort zählen
        # nur die ausgegebenen Bilder.
        ffmpeg._read_progress_line("out_time_us=30000000\n", 60.0, 40)
        assert progress.snapshot()[0]["fraction"] is None
        ffmpeg._read_progress_line("frame=10\n", 60.0, 40)
        assert progress.snapshot()[0]["fraction"] == 0.25

    def test_geschwindigkeit_und_bildrate(self):
        ffmpeg._read_progress_line("speed=1.75x\n", 60.0, None)
        ffmpeg._read_progress_line("fps=25.5\n", 60.0, None)
        daten = progress.snapshot()[0]
        assert daten["speed"] == 1.75
        assert daten["fps"] == 25.5

    def test_unbrauchbare_zeilen(self):
        for zeile in ("speed=N/A\n", "out_time_us=\n", "progress=continue\n", "kaputt\n"):
            ffmpeg._read_progress_line(zeile, 60.0, None)
        assert progress.snapshot()[0]["fraction"] is None


@needs_ffmpeg
class TestEchterDurchlauf:
    def test_ffmpeg_meldet_zwischenstaende(self, tmp_path: Path):
        ziel = tmp_path / "out.mp4"
        args = ffmpeg.base_command() + [
            "-f", "lavfi",
            "-i", "testsrc2=size=320x180:rate=25:duration=3",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-pix_fmt", "yuv420p",
            str(ziel),
        ]
        progress.begin(11, "proxy", filename="test.mp4", duration=3.0)
        ffmpeg.run(args, timeout=120, total_seconds=3.0)

        daten = progress.snapshot()[0]
        assert ziel.exists()
        assert daten["fraction"] and daten["fraction"] > 0

    def test_fehler_bleibt_ein_ffmpeg_fehler(self, tmp_path: Path):
        progress.begin(12, "proxy", duration=3.0)
        args = ffmpeg.base_command() + ["-i", str(tmp_path / "gibtsnicht.mov"), "-f", "null", "-"]
        with pytest.raises(ffmpeg.FFmpegError):
            ffmpeg.run(args, timeout=60, total_seconds=3.0)

    def test_zeitlimit_bricht_ab(self, tmp_path: Path):
        # Endlose Quelle ohne Ende, nur der Wecker kann hier abbrechen
        progress.begin(13, "proxy", duration=9999.0)
        args = ffmpeg.base_command() + [
            "-f", "lavfi",
            "-i", "testsrc2=size=320x180:rate=25",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-f", "null", "-",
        ]
        with pytest.raises(ffmpeg.FFmpegError, match="Zeitlimit"):
            ffmpeg.run(args, timeout=2, total_seconds=9999.0)


class TestWarteschlangeNachArt:
    def test_gruppiert_und_beschriftet(self):
        clip_id = insert_clip("Rushes/a.mp4")
        conn = jobs.get_conn()
        conn.execute(
            "INSERT INTO jobs(type, clip_id, priority, state) VALUES ('proxy', ?, 40, 'queued')",
            (clip_id,),
        )
        conn.execute(
            "INSERT INTO jobs(type, priority, state) VALUES ('embed', 50, 'queued')"
        )
        conn.execute(
            "INSERT INTO jobs(type, priority, state) VALUES ('probe', 10, 'running')"
        )

        nach_art = {eintrag["type"]: eintrag for eintrag in jobs.queue_by_type()}
        assert nach_art["proxy"]["queued"] == 1
        assert nach_art["probe"]["running"] == 1
        assert nach_art["embed"]["label"] == "Bildanalyse"
        # Reihenfolge der Verarbeitungskette, nicht alphabetisch
        assert [e["type"] for e in jobs.queue_by_type()] == ["probe", "proxy", "embed"]


class TestEndpunkt:
    @pytest.fixture
    def client(self, media_root):
        from app.main import app

        with TestClient(app) as test_client:
            test_client.post(
                "/api/auth/login", json={"username": "tester", "password": "geheim"}
            )
            yield test_client

    def test_liefert_alle_abschnitte(self, client: TestClient):
        daten = client.get("/api/progress").json()
        for schluessel in (
            "active",
            "queue",
            "by_type",
            "pending",
            "recent",
            "failed",
            "scanning",
            "scan",
            "worker_count",
        ):
            assert schluessel in daten

    def test_zeigt_laufende_arbeit(self, client: TestClient):
        clip_id = insert_clip("Rushes/gross.mp4")
        progress.begin(21, "proxy", clip_id, filename="gross.mp4", duration=30.0)
        progress.report(fraction=0.25, speed=1.2)

        daten = client.get("/api/progress").json()
        laufend = daten["active"][0]
        assert laufend["filename"] == "gross.mp4"
        assert laufend["fraction"] == 0.25
        assert laufend["label"] == "Vorschau berechnen"

    def test_fehlgeschlagene_jobs_mit_dateiname(self, client: TestClient):
        clip_id = insert_clip("Rushes/kaputt.mp4")
        jobs.get_conn().execute(
            "INSERT INTO jobs(type, clip_id, state, attempts, error) "
            "VALUES ('proxy', ?, 'failed', 3, 'ffmpeg beendet mit Code 1')",
            (clip_id,),
        )

        eintrag = client.get("/api/progress").json()["failed"][0]
        assert eintrag["filename"] == "kaputt.mp4"
        assert eintrag["attempts"] == 3
        assert "ffmpeg" in eintrag["error"]

    def test_ohne_anmeldung_gesperrt(self, media_root):
        from app.main import app

        with TestClient(app) as anonym:
            assert anonym.get("/api/progress").status_code == 401


@needs_ffmpeg
def test_hat_ffprobe():
    """Absicherung, dass die ffmpeg-Tests oben überhaupt etwas prüfen."""
    assert subprocess.run(
        [settings.ffmpeg_path, "-version"], capture_output=True
    ).returncode == 0
