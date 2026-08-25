"""Tests für die Vorschläge im Suchfeld.

Der Kern: Getippt wird ein Wortanfang, angeboten wird der Filter, der zum
Ziel führt (Tag, Objektiv, Ordner, Look, Sammlung), nicht nur der
Volltexttreffer.
"""

from __future__ import annotations

from app.db import get_conn
from app.library import ensure_tag, set_auto_tags
from app.search.suggest import suggest
from helpers import insert_clip


def tag_clip(clip_id: int, name: str, category: str = "custom") -> None:
    conn = get_conn()
    tag_id = ensure_tag(conn, name, category)
    conn.execute(
        "INSERT OR IGNORE INTO clip_tags(clip_id, tag_id, source) VALUES (?, ?, 'manual')",
        (clip_id, tag_id),
    )


def kinds(items: list[dict], kind: str) -> list[dict]:
    return [item for item in items if item["kind"] == kind]


class TestTags:
    def test_findet_tag_ueber_wortanfang(self):
        clip_id = insert_clip("Rushes/a.mp4")
        tag_clip(clip_id, "Raspberry Pi")

        items = suggest("rasp")
        assert [item["value"] for item in kinds(items, "tag")] == ["Raspberry Pi"]
        assert kinds(items, "tag")[0]["count"] == 1
        assert kinds(items, "tag")[0]["group"] == "Eigene Tags"

    def test_findet_tag_auch_mitten_im_wort(self):
        clip_id = insert_clip("Rushes/a.mp4")
        tag_clip(clip_id, "Raspberry Pi")
        assert kinds(suggest("berry"), "tag")

    def test_objektiv_bekommt_eigene_gruppe(self):
        clip_id = insert_clip("Rushes/a.mp4")
        tag_clip(clip_id, "Sigma 24-70mm F2.8", "lens")

        treffer = kinds(suggest("sigma"), "tag")
        assert treffer[0]["group"] == "Objektiv"
        assert treffer[0]["category"] == "lens"

    def test_kamera_wird_vorgeschlagen(self):
        clip_id = insert_clip("Rushes/a.mp4", camera_label="Sony FX3")
        set_auto_tags(get_conn(), clip_id, [("Sony FX3", "camera")])

        treffer = kinds(suggest("fx3"), "tag")
        assert treffer[0]["value"] == "Sony FX3"
        assert treffer[0]["group"] == "Kamera"

    def test_grosskleinschreibung_und_umlaute(self):
        clip_id = insert_clip("Rushes/a.mp4")
        tag_clip(clip_id, "Öltank")
        assert kinds(suggest("ölt"), "tag")
        assert kinds(suggest("ÖLT"), "tag")

    def test_verwaistes_tag_wird_nicht_angeboten(self):
        # Ein Tag ohne Clips wäre als Filter eine Sackgasse
        ensure_tag(get_conn(), "Geistertag", "custom")
        assert not kinds(suggest("geister"), "tag")

    def test_fehlende_dateien_zaehlen_nicht_mit(self):
        vorhanden = insert_clip("Rushes/a.mp4")
        verschwunden = insert_clip("Rushes/b.mp4", status="missing")
        tag_clip(vorhanden, "Drohne")
        tag_clip(verschwunden, "Drohne")
        assert kinds(suggest("drohne"), "tag")[0]["count"] == 1

    def test_haeufigeres_tag_steht_oben(self):
        selten = insert_clip("Rushes/a.mp4")
        tag_clip(selten, "Sonnenaufgang")
        for index in range(3):
            clip_id = insert_clip(f"Rushes/b{index}.mp4")
            tag_clip(clip_id, "Sonnenuntergang")

        namen = [item["value"] for item in kinds(suggest("sonnen"), "tag")]
        assert namen == ["Sonnenuntergang", "Sonnenaufgang"]


class TestWeitereQuellen:
    def test_ordner(self):
        insert_clip("Reisen/Island/a.mp4")
        treffer = kinds(suggest("island"), "folder")
        assert treffer[0]["value"] == "Reisen/Island"
        assert treffer[0]["count"] == 1

    def test_dateiname_liefert_clip_id(self):
        clip_id = insert_clip("Rushes/Sonnenuntergang.mp4")
        treffer = kinds(suggest("sonnenunter"), "clip")
        assert treffer[0]["clip_id"] == clip_id
        assert treffer[0]["detail"] == "Rushes"

    def test_bildlook(self):
        insert_clip("Rushes/a.mp4", look="log")
        treffer = kinds(suggest("log"), "look")
        assert treffer[0]["value"] == "log"
        assert treffer[0]["label"] == "LOG"

    def test_manuell_gesetzter_look_gewinnt(self):
        insert_clip("Rushes/a.mp4", look="rec709", look_manual="log")
        assert kinds(suggest("log"), "look")[0]["count"] == 1

    def test_sammlung(self):
        conn = get_conn()
        cursor = conn.execute("INSERT INTO collections(name) VALUES ('Island 2026')")
        clip_id = insert_clip("Rushes/a.mp4")
        conn.execute(
            "INSERT INTO collection_clips(collection_id, clip_id) VALUES (?, ?)",
            (cursor.lastrowid, clip_id),
        )
        treffer = kinds(suggest("island"), "collection")
        assert treffer[0]["value"] == str(cursor.lastrowid)
        assert treffer[0]["count"] == 1

    def test_schnellzugriff_favoriten(self):
        insert_clip("Rushes/a.mp4", favorite=1)
        treffer = kinds(suggest("favo"), "quick")
        assert treffer[0]["value"] == "favorite"

    def test_schnellzugriff_ohne_treffer_bleibt_weg(self):
        insert_clip("Rushes/a.mp4")
        assert not kinds(suggest("favo"), "quick")


class TestReihenfolgeUndGrenzen:
    def test_leere_eingabe_liefert_nichts(self):
        insert_clip("Rushes/a.mp4")
        assert suggest("") == []
        assert suggest("   ") == []

    def test_treffer_am_wortanfang_steht_vor_treffer_in_der_mitte(self):
        erster = insert_clip("Rushes/a.mp4")
        zweiter = insert_clip("Rushes/b.mp4")
        tag_clip(erster, "Berlin")
        tag_clip(zweiter, "Oberlicht")

        namen = [item["value"] for item in kinds(suggest("berl"), "tag")]
        assert namen[0] == "Berlin"

    def test_gesamtzahl_ist_gedeckelt(self):
        for index in range(30):
            clip_id = insert_clip(f"Testordner/clip{index}.mp4")
            tag_clip(clip_id, f"Testtag {index}")
        assert len(suggest("test", limit=8)) <= 8

    def test_dateinamen_verdraengen_die_tags_nicht(self):
        # Ohne Deckel je Art würden zwölf gleichnamige Dateien das Tag
        # aus der Liste schieben, obwohl es der nützlichere Filter ist.
        for index in range(12):
            insert_clip(f"Rushes/Sonne{index}.mp4")
        clip_id = insert_clip("Rushes/x.mp4")
        tag_clip(clip_id, "Sonne")

        items = suggest("sonne")
        assert kinds(items, "tag")
        assert len(kinds(items, "clip")) <= 5

    def test_prozentzeichen_bleibt_harmlos(self):
        insert_clip("Rushes/a.mp4")
        assert suggest("%") == []
