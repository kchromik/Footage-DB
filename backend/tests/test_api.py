"""Integrationstest ueber die ganze Kette: Scan, Vorschau, Suche, Upload, Download."""

from __future__ import annotations

import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from conftest import make_clip, needs_ffmpeg


def wait_for_queue(client: TestClient, timeout: float = 120.0) -> dict:
    """Wartet, bis Scan und alle Hintergrundaufgaben durch sind.

    Der Scan laeuft in einem eigenen Thread und reiht seine Jobs erst nach und
    nach ein. Deshalb reicht "Warteschlange gerade leer" nicht aus, es muss
    mehrmals hintereinander ruhig sein.
    """
    deadline = time.time() + timeout
    stats: dict = {}
    stable = 0
    while time.time() < deadline:
        stats = client.get("/api/stats").json()
        idle = (
            stats["queue"]["queued"] == 0
            and stats["queue"]["running"] == 0
            and not stats["scanning"]
        )
        stable = stable + 1 if idle else 0
        if stable >= 4:
            return stats
        time.sleep(0.3)
    raise AssertionError(f"Warteschlange wurde nicht leer: {stats}")


@pytest.fixture
def client(media_root):
    from app.main import app

    with TestClient(app) as test_client:
        test_client.post(
            "/api/auth/login", json={"username": "tester", "password": "geheim"}
        )
        yield test_client


class TestAnmeldung:
    def test_ohne_anmeldung_gesperrt(self, media_root):
        from app.main import app

        with TestClient(app) as anonymous:
            assert anonymous.get("/api/clips").status_code == 401

    def test_falsches_passwort(self, media_root):
        from app.main import app

        with TestClient(app) as anonymous:
            response = anonymous.post(
                "/api/auth/login", json={"username": "tester", "password": "falsch"}
            )
            assert response.status_code == 401

    def test_health_ist_offen(self, media_root):
        from app.main import app

        with TestClient(app) as anonymous:
            assert anonymous.get("/api/health").json() == {"status": "ok"}


@needs_ffmpeg
class TestKompletterDurchlauf:
    def test_scan_bis_download(self, client, media_root):
        make_clip(media_root / "Rushes" / "C0001.MP4", seconds=2.0, size="640x360", audio=True)
        make_clip(media_root / "Export" / "Intro_final.mp4", seconds=1.0, size="320x180")

        assert client.post("/api/scan").json()["started"] is True
        wait_for_queue(client)

        page = client.get("/api/clips?with_facets=true").json()
        assert page["total"] == 2
        namen = {item["filename"] for item in page["items"]}
        assert namen == {"C0001.MP4", "Intro_final.mp4"}

        clip = next(item for item in page["items"] if item["filename"] == "C0001.MP4")
        assert clip["width"] == 640
        assert clip["height"] == 360
        assert clip["duration"] == pytest.approx(2.0, abs=0.3)
        assert clip["video_codec"] == "h264"
        assert clip["audio_codec"] == "aac"
        assert clip["camera"] == "Sony"  # aus dem Dateinamen C0001 abgeleitet
        assert clip["poster_status"] == "ready"
        assert clip["poster_url"]
        assert clip["playable"] is True

        # Facetten enthalten die automatisch vergebenen Tags
        assert "tech" in page["facets"]["tags"]
        tech = {entry["name"] for entry in page["facets"]["tags"]["tech"]}
        assert "H.264" in tech

        # Der Export wird als graded erkannt, das Rohmaterial nicht
        export = next(item for item in page["items"] if item["filename"] == "Intro_final.mp4")
        assert export["look"] == "graded"

        # Vorschaubild wird ausgeliefert
        poster = client.get(f"/api/media/{clip['id']}/poster")
        assert poster.status_code == 200
        assert poster.headers["content-type"] == "image/webp"
        assert len(poster.content) > 500

        # Sprite fuer die Vorschau beim Drueberfahren
        assert clip["sprite"] is not None
        assert clip["sprite"]["count"] >= 4
        sprite = client.get(f"/api/media/{clip['id']}/sprite")
        assert sprite.status_code == 200

        # Original bitgleich herunterladen
        source = media_root / clip["path"]
        download = client.get(f"/api/media/{clip['id']}/download")
        assert download.status_code == 200
        assert "attachment" in download.headers["content-disposition"]
        assert hashlib.sha256(download.content).hexdigest() == hashlib.sha256(
            source.read_bytes()
        ).hexdigest()

        # Range-Anfrage, damit der Player springen kann
        partial = client.get(
            f"/api/media/{clip['id']}/play", headers={"Range": "bytes=0-99"}
        )
        assert partial.status_code == 206
        assert partial.headers["content-range"].startswith("bytes 0-99/")
        assert len(partial.content) == 100

    def test_suche_und_filter(self, client, media_root):
        make_clip(media_root / "Rushes" / "Sonnenuntergang.MP4", size="320x180")
        make_clip(media_root / "Rushes" / "C0002.MP4", size="320x180")
        client.post("/api/scan")
        wait_for_queue(client)

        treffer = client.get("/api/clips?q=sonnen&mode=text").json()
        assert treffer["total"] == 1
        assert treffer["items"][0]["filename"] == "Sonnenuntergang.MP4"

        leer = client.get("/api/clips?q=giraffe&mode=text").json()
        assert leer["total"] == 0

        nach_kamera = client.get("/api/clips?tag=Sony").json()
        assert nach_kamera["total"] == 1

    def test_bearbeiten_und_stapelaktion(self, client, media_root):
        make_clip(media_root / "a.mp4", size="320x180")
        make_clip(media_root / "b.mp4", size="320x180")
        client.post("/api/scan")
        wait_for_queue(client)

        ids = [item["id"] for item in client.get("/api/clips").json()["items"]]

        geaendert = client.patch(
            f"/api/clips/{ids[0]}",
            json={"favorite": True, "notes": "Titelbild", "tags": ["Intro", "Berlin"]},
        ).json()
        assert geaendert["favorite"] is True
        assert geaendert["notes"] == "Titelbild"
        assert {"Intro", "Berlin"} <= {tag["name"] for tag in geaendert["tags"]}

        # Ueber ein manuell gesetztes Tag laesst sich suchen
        assert client.get("/api/clips?q=Berlin&mode=text").json()["total"] == 1
        assert client.get("/api/clips?favorite=true").json()["total"] == 1

        # Manuelle Look-Korrektur gewinnt gegen die Automatik
        korrigiert = client.patch(f"/api/clips/{ids[1]}", json={"look_manual": "hdr"}).json()
        assert korrigiert["look"] == "hdr"
        assert korrigiert["look_manual"] == "hdr"
        assert client.get("/api/clips?look=hdr").json()["total"] == 1

        # Stapelaktion auf beide Clips
        result = client.post(
            "/api/clips/batch/tags", json={"clip_ids": ids, "add": ["Projekt-42"]}
        ).json()
        assert result["changed"] == 2
        assert client.get("/api/clips?tag=Projekt-42").json()["total"] == 2

    def test_upload_mit_wiederaufnahme(self, client, media_root, tmp_path):
        quelle = make_clip(tmp_path / "Neu.MP4", seconds=1.0, size="320x180")
        daten = quelle.read_bytes()

        init = client.post(
            "/api/uploads/init", json={"filename": "Neu.MP4", "size": len(daten)}
        ).json()
        chunk_size = init["chunk_size"]

        # Erster Block, danach so tun als waere die Verbindung weg
        client.put(f"/api/uploads/{init['id']}/chunk/0", content=daten[:chunk_size])

        fortsetzung = client.post(
            "/api/uploads/init", json={"filename": "Neu.MP4", "size": len(daten)}
        ).json()
        assert fortsetzung["resumed"] is True
        assert fortsetzung["received"] == [0]

        for index in range(1, fortsetzung["chunk_count"]):
            teil = daten[index * chunk_size : (index + 1) * chunk_size]
            client.put(f"/api/uploads/{fortsetzung['id']}/chunk/{index}", content=teil)

        fertig = client.post(f"/api/uploads/{fortsetzung['id']}/complete").json()
        ziel = media_root / fertig["path"]
        assert ziel.exists()
        assert ziel.read_bytes() == daten
        # Automatisch nach Jahr/Monat/Kamera einsortiert
        assert fertig["path"].count("/") == 3

    def test_unvollstaendiger_upload_wird_abgelehnt(self, client, media_root):
        init = client.post(
            "/api/uploads/init", json={"filename": "Halb.MP4", "size": 20_000_000}
        ).json()
        antwort = client.post(f"/api/uploads/{init['id']}/complete")
        assert antwort.status_code == 409
        assert "unvollstaendig" in antwort.json()["detail"]

    def test_falscher_dateityp_wird_abgelehnt(self, client):
        antwort = client.post(
            "/api/uploads/init", json={"filename": "notizen.txt", "size": 100}
        )
        assert antwort.status_code == 400

    def test_fehlende_datei_wird_erkannt(self, client, media_root):
        make_clip(media_root / "weg.mp4", size="320x180")
        client.post("/api/scan")
        wait_for_queue(client)
        assert client.get("/api/clips").json()["total"] == 1

        (media_root / "weg.mp4").unlink()
        client.post("/api/scan")
        wait_for_queue(client)

        assert client.get("/api/clips").json()["total"] == 0
        assert client.get("/api/clips?only_missing=true").json()["total"] == 1
        assert client.get("/api/stats").json()["missing"] == 1

    def test_verschobene_datei_behaelt_ihre_tags(self, client, media_root):
        make_clip(media_root / "alt" / "clip.mp4", size="320x180")
        client.post("/api/scan")
        wait_for_queue(client)

        clip = client.get("/api/clips").json()["items"][0]
        client.patch(f"/api/clips/{clip['id']}", json={"tags": ["Wichtig"]})

        ziel = media_root / "neu" / "clip.mp4"
        ziel.parent.mkdir(parents=True)
        (media_root / "alt" / "clip.mp4").rename(ziel)

        client.post("/api/scan")
        wait_for_queue(client)

        danach = client.get("/api/clips").json()
        assert danach["total"] == 1
        assert danach["items"][0]["id"] == clip["id"]
        assert danach["items"][0]["path"] == "neu/clip.mp4"
        assert "Wichtig" in {tag["name"] for tag in danach["items"][0]["tags"]}

    def test_zip_download(self, client, media_root):
        make_clip(media_root / "a.mp4", size="320x180")
        make_clip(media_root / "b.mp4", size="320x180")
        client.post("/api/scan")
        wait_for_queue(client)

        ids = [item["id"] for item in client.get("/api/clips").json()["items"]]
        antwort = client.get(f"/api/media/zip?ids={','.join(map(str, ids))}")
        assert antwort.status_code == 200
        assert antwort.headers["content-type"] == "application/zip"
        assert antwort.content[:2] == b"PK"

    def test_einsortieren_ueber_die_api(self, client, media_root):
        make_clip(media_root / "Rushes" / "C0001.MP4", size="320x180")
        client.post("/api/scan")
        wait_for_queue(client)

        plan = client.post("/api/organize/plan", json={}).json()
        assert plan["count"] == 1
        assert plan["preview"][0]["to"].endswith("/C0001.MP4")
        assert "Sony" in plan["preview"][0]["to"]

        # Ohne Bestaetigung passiert nichts
        assert client.post("/api/organize/apply", json={"confirm": False}).status_code == 400

        ergebnis = client.post("/api/organize/apply", json={"confirm": True}).json()
        assert ergebnis["moved"] == 1
        assert not (media_root / "Rushes").exists()

        zurueck = client.post(f"/api/organize/undo/{ergebnis['batch']}").json()
        assert zurueck["reverted"] == 1
        assert (media_root / "Rushes" / "C0001.MP4").exists()
