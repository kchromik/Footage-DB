"""Tests für den Einrichtungsassistenten und die Einstellungen zur Laufzeit."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.settings_store import hash_password, runtime, verify_password


@pytest.fixture
def fresh(media_root, monkeypatch):
    """Instanz ohne Passwort in der .env, wie direkt nach der Installation."""
    monkeypatch.setattr(settings, "auth_password", "")
    runtime.reload()
    from app.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def mit_env_passwort(media_root):
    from app.main import app

    with TestClient(app) as client:
        yield client


class TestPasswortHash:
    def test_hash_und_pruefung(self):
        stored = hash_password("geheimnis123")
        assert stored.startswith("scrypt$")
        assert verify_password("geheimnis123", stored)
        assert not verify_password("falsch", stored)

    def test_zwei_hashes_sind_verschieden(self):
        # zufälliges Salz pro Aufruf
        assert hash_password("gleich") != hash_password("gleich")

    def test_kaputter_hash_wird_abgelehnt(self):
        assert not verify_password("egal", "unsinn")
        assert not verify_password("egal", "md5$1$2$3$4$5")


class TestOhnePasswort:
    def test_status_meldet_offene_einrichtung(self, fresh):
        status = fresh.get("/api/setup/status").json()
        assert status["complete"] is False
        assert status["has_password"] is False
        assert status["media_root"] == str(settings.media_root)

    def test_pruefung_ist_ohne_anmeldung_erreichbar(self, fresh):
        check = fresh.get("/api/setup/check").json()
        assert check["media"]["exists"] is True
        assert check["data"]["writable"] is True
        assert check["cpu_count"] >= 1
        assert isinstance(check["warnings"], list)

    def test_vorschau_zaehlt_dateien(self, fresh, media_root):
        from conftest import HAS_FFMPEG, make_clip

        if not HAS_FFMPEG:
            pytest.skip("ffmpeg fehlt")
        make_clip(media_root / "Rushes" / "a.mp4", size="160x90")
        make_clip(media_root / "b.mp4", size="160x90")

        preview = fresh.get("/api/setup/preview").json()
        assert preview["count"] == 2
        namen = {folder["name"] for folder in preview["folders"]}
        assert namen == {"Rushes", "(Wurzelordner)"}
        assert preview["estimate_minutes"] >= 1

    def test_schema_vorschau(self, fresh):
        antwort = fresh.post(
            "/api/setup/pattern-preview", json={"pattern": "{year}/{camera}"}
        ).json()
        assert antwort["example"] == "2026/Sony-FX3/C0042.MP4"

    def test_unbekannter_platzhalter(self, fresh):
        antwort = fresh.post("/api/setup/pattern-preview", json={"pattern": "{unsinn}"})
        assert antwort.status_code == 400

    def test_abschluss_setzt_passwort_und_einstellungen(self, fresh):
        antwort = fresh.post(
            "/api/setup/complete",
            json={
                "auth_user": "kevin",
                "password": "supergeheim",
                "proxy_height": 1080,
                "proxy_crf": 24,
                "hwaccel": "off",
                "semantic_enabled": False,
                "worker_count": 3,
                "organize_uploads": False,
                "organize_pattern": "{year}/{camera}",
                "rescan_interval_minutes": 0,
                "start_scan": False,
            },
        )
        assert antwort.status_code == 200
        assert antwort.json()["complete"] is True

        assert runtime.setup_complete is True
        assert runtime.auth_user == "kevin"
        assert runtime.proxy_height == 1080
        assert runtime.hwaccel == "off"
        assert runtime.semantic_enabled is False
        assert runtime.worker_count == 3
        assert runtime.organize_uploads is False
        assert runtime.organize_pattern == "{year}/{camera}"
        assert runtime.rescan_interval_minutes == 0
        assert verify_password("supergeheim", runtime.password_hash)

        # Der Assistent hält die Sitzung offen, sonst fände man sich sofort
        # im Anmeldebildschirm wieder
        assert fresh.get("/api/clips").status_code == 200

    def test_zu_kurzes_passwort(self, fresh):
        antwort = fresh.post("/api/setup/complete", json={"password": "kurz"})
        assert antwort.status_code == 400
        assert "8 Zeichen" in antwort.json()["detail"]

    def test_nach_abschluss_ist_die_einrichtung_geschuetzt(self, fresh):
        fresh.post("/api/setup/complete", json={"password": "supergeheim"})
        fresh.post("/api/auth/logout")
        assert fresh.get("/api/setup/check").status_code == 401
        assert fresh.post("/api/setup/complete", json={}).status_code == 401

    def test_anmeldung_mit_dem_neuen_passwort(self, fresh):
        fresh.post(
            "/api/setup/complete",
            json={"auth_user": "kevin", "password": "supergeheim"},
        )
        fresh.post("/api/auth/logout")

        assert (
            fresh.post(
                "/api/auth/login", json={"username": "kevin", "password": "falsch"}
            ).status_code
            == 401
        )
        assert (
            fresh.post(
                "/api/auth/login", json={"username": "kevin", "password": "supergeheim"}
            ).status_code
            == 200
        )


class TestMitEnvPasswort:
    def test_einrichtung_verlangt_anmeldung(self, mit_env_passwort):
        status = mit_env_passwort.get("/api/setup/status").json()
        assert status["has_password"] is True
        assert status["password_from_env"] is True

        client = mit_env_passwort
        client.cookies.clear()
        assert client.get("/api/setup/check").status_code == 401

        client.post("/api/auth/login", json={"username": "tester", "password": "geheim"})
        assert client.get("/api/setup/check").status_code == 200


class TestEinstellungen:
    def test_lesen_und_aendern(self, mit_env_passwort):
        client = mit_env_passwort
        client.post("/api/auth/login", json={"username": "tester", "password": "geheim"})

        werte = client.get("/api/settings").json()
        assert werte["proxy_height"] == settings.proxy_height

        geändert = client.patch("/api/settings", json={"proxy_height": 540}).json()
        assert geändert["proxy_height"] == 540
        assert runtime.proxy_height == 540

    def test_ungueltige_werte(self, mit_env_passwort):
        client = mit_env_passwort
        client.post("/api/auth/login", json={"username": "tester", "password": "geheim"})
        assert client.patch("/api/settings", json={"proxy_height": 99}).status_code == 422
        assert client.patch("/api/settings", json={"hwaccel": "quatsch"}).status_code == 400

    def test_datenbank_gewinnt_gegen_env(self, mit_env_passwort):
        client = mit_env_passwort
        client.post("/api/auth/login", json={"username": "tester", "password": "geheim"})
        client.patch("/api/settings", json={"password": "neuespasswort"})

        # Ab jetzt gilt der Hash aus der Datenbank
        client.post("/api/auth/logout")
        assert (
            client.post(
                "/api/auth/login", json={"username": "tester", "password": "geheim"}
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/api/auth/login", json={"username": "tester", "password": "neuespasswort"}
            ).status_code
            == 200
        )

    def test_einstellungen_brauchen_anmeldung(self, mit_env_passwort):
        mit_env_passwort.cookies.clear()
        assert mit_env_passwort.get("/api/settings").status_code == 401
