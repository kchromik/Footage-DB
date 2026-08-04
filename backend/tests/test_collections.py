"""Tests für Sammlungen und die Suche nach ähnlichen Clips."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.db import get_conn
from app.search import semantic
from app.search.clip_model import EMBED_DIM
from app.search.query import ClipFilters, build_where
from helpers import insert_clip


@pytest.fixture
def client(media_root):
    from app.main import app

    with TestClient(app) as test_client:
        test_client.post(
            "/api/auth/login", json={"username": "tester", "password": "geheim"}
        )
        yield test_client


class TestSammlungen:
    def test_anlegen_und_auflisten(self, client):
        angelegt = client.post("/api/collections", json={"name": "Reise Japan"}).json()
        assert angelegt["name"] == "Reise Japan"
        assert angelegt["count"] == 0

        liste = client.get("/api/collections").json()["items"]
        assert [entry["name"] for entry in liste] == ["Reise Japan"]

    def test_doppelter_name_wird_abgelehnt(self, client):
        client.post("/api/collections", json={"name": "Intro"})
        antwort = client.post("/api/collections", json={"name": "Intro"})
        assert antwort.status_code == 409

    def test_umbenennen(self, client):
        angelegt = client.post("/api/collections", json={"name": "Alt"}).json()
        umbenannt = client.patch(
            f"/api/collections/{angelegt['id']}", json={"name": "Neu"}
        ).json()
        assert umbenannt["name"] == "Neu"

    def test_clip_darf_in_mehreren_sammlungen_liegen(self, client):
        clip_id = insert_clip("Rushes/a.mp4")
        erste = client.post("/api/collections", json={"name": "Projekt A"}).json()
        zweite = client.post("/api/collections", json={"name": "Projekt B"}).json()

        for sammlung in (erste, zweite):
            antwort = client.post(
                f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [clip_id]}
            ).json()
            assert antwort["added"] == 1

        detail = client.get(f"/api/clips/{clip_id}").json()
        assert {entry["name"] for entry in detail["collections"]} == {
            "Projekt A",
            "Projekt B",
        }

    def test_doppeltes_hinzufuegen_zaehlt_nicht_doppelt(self, client):
        clip_id = insert_clip("a.mp4")
        sammlung = client.post("/api/collections", json={"name": "Projekt"}).json()
        client.post(f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [clip_id]})
        zweiter = client.post(
            f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [clip_id]}
        ).json()
        assert zweiter["added"] == 0
        assert zweiter["collection"]["count"] == 1

    def test_unbekannter_clip_wird_uebersprungen(self, client):
        sammlung = client.post("/api/collections", json={"name": "Projekt"}).json()
        antwort = client.post(
            f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [9999]}
        )
        assert antwort.status_code == 200
        assert antwort.json()["added"] == 0

    def test_filter_liefert_nur_mitglieder(self, client):
        drin = insert_clip("a.mp4")
        draussen = insert_clip("b.mp4")
        sammlung = client.post("/api/collections", json={"name": "Projekt"}).json()
        client.post(f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [drin]})

        seite = client.get(f"/api/clips?collection={sammlung['id']}").json()
        assert [entry["id"] for entry in seite["items"]] == [drin]
        assert draussen not in [entry["id"] for entry in seite["items"]]

    def test_sortierung_folgt_der_reihenfolge_beim_hinzufuegen(self, client):
        # Absichtlich gegen die Standardsortierung: zuerst der neuere Clip
        neu = insert_clip("neu.mp4", recorded_at="2026-07-14T10:00:00")
        alt = insert_clip("alt.mp4", recorded_at="2020-01-01T10:00:00")
        sammlung = client.post("/api/collections", json={"name": "Schnitt"}).json()
        client.post(
            f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [neu, alt]}
        )

        seite = client.get(
            f"/api/clips?collection={sammlung['id']}&sort=collection_pos"
        ).json()
        assert [entry["id"] for entry in seite["items"]] == [neu, alt]

    def test_entfernen(self, client):
        clip_id = insert_clip("a.mp4")
        sammlung = client.post("/api/collections", json={"name": "Projekt"}).json()
        client.post(f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [clip_id]})

        antwort = client.request(
            "DELETE",
            f"/api/collections/{sammlung['id']}/clips",
            json={"clip_ids": [clip_id]},
        ).json()
        assert antwort["removed"] == 1
        assert client.get(f"/api/collections/{sammlung['id']}").json()["count"] == 0

    def test_loeschen_laesst_clips_unangetastet(self, client):
        clip_id = insert_clip("a.mp4")
        sammlung = client.post("/api/collections", json={"name": "Projekt"}).json()
        client.post(f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [clip_id]})

        client.delete(f"/api/collections/{sammlung['id']}")
        assert client.get(f"/api/collections/{sammlung['id']}").status_code == 404
        assert client.get(f"/api/clips/{clip_id}").status_code == 200

    def test_geloeschter_clip_faellt_aus_der_sammlung(self, client):
        clip_id = insert_clip("a.mp4")
        sammlung = client.post("/api/collections", json={"name": "Projekt"}).json()
        client.post(f"/api/collections/{sammlung['id']}/clips", json={"clip_ids": [clip_id]})

        client.delete(f"/api/clips/{clip_id}")
        assert client.get(f"/api/collections/{sammlung['id']}").json()["count"] == 0

    def test_filter_greift_auch_ohne_api(self):
        clip_id = insert_clip("a.mp4")
        conn = get_conn()
        conn.execute("INSERT INTO collections(name) VALUES ('Projekt')")
        conn.execute(
            "INSERT INTO collection_clips(collection_id, clip_id) VALUES (1, ?)",
            (clip_id,),
        )
        where, params = build_where(ClipFilters(collection=1))
        rows = conn.execute(f"SELECT c.id FROM clips c WHERE {where}", params).fetchall()
        assert [row["id"] for row in rows] == [clip_id]


def _store_embedding(clip_id: int, vector: np.ndarray) -> None:
    """Legt einen Bildvektor ab, ohne das CLIP-Modell zu bemühen."""
    vector = (vector / np.linalg.norm(vector)).astype(np.float32)
    get_conn().execute(
        "INSERT INTO embeddings(clip_id, model, dim, vector) VALUES (?, 'test', ?, ?)",
        (clip_id, EMBED_DIM, vector.astype(np.float16).tobytes()),
    )
    get_conn().execute("UPDATE clips SET embed_status='ready' WHERE id=?", (clip_id,))


class TestAehnlicheClips:
    def _vektoren(self) -> tuple[int, int, int]:
        basis = np.zeros(EMBED_DIM, dtype=np.float32)
        basis[0] = 1.0
        fast_gleich = basis.copy()
        fast_gleich[1] = 0.2
        senkrecht = np.zeros(EMBED_DIM, dtype=np.float32)
        senkrecht[5] = 1.0

        referenz = insert_clip("a.mp4")
        nah = insert_clip("b.mp4")
        fern = insert_clip("c.mp4")
        _store_embedding(referenz, basis)
        _store_embedding(nah, fast_gleich)
        _store_embedding(fern, senkrecht)
        semantic.index.load(force=True)
        return referenz, nah, fern

    def test_findet_nahen_clip_und_laesst_sich_selbst_aus(self, client):
        referenz, nah, fern = self._vektoren()
        items = client.get(f"/api/clips/{referenz}/similar").json()["items"]
        ids = [entry["id"] for entry in items]
        assert ids == [nah]
        assert fern not in ids
        assert referenz not in ids

    def test_ohne_bildvektor_leere_liste(self, client):
        clip_id = insert_clip("ohne.mp4")
        semantic.index.load(force=True)
        antwort = client.get(f"/api/clips/{clip_id}/similar").json()
        assert antwort["items"] == []
        assert antwort["status"] == "pending"

    def test_fehlende_datei_taucht_nicht_auf(self, client):
        referenz, nah, _ = self._vektoren()
        get_conn().execute("UPDATE clips SET status='missing' WHERE id=?", (nah,))
        items = client.get(f"/api/clips/{referenz}/similar").json()["items"]
        assert items == []

    def test_unbekannter_clip(self, client):
        assert client.get("/api/clips/9999/similar").status_code == 404
