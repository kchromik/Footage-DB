"""Tests für Suchabfragen, Facetten und Volltextindex."""

from __future__ import annotations

from app.db import get_conn, reindex_fts
from app.library import ensure_tag, set_auto_tags
from app.search.query import ClipFilters, build_where, facets, fts_expression, text_match_ids
from helpers import insert_clip


class TestFtsExpression:
    def test_praefixsuche(self):
        assert fts_expression("sonne") == '"sonne"*'

    def test_mehrere_woerter_werden_verundet(self):
        assert fts_expression("sonne strand") == '"sonne"* AND "strand"*'

    def test_sonderzeichen_werden_entfernt(self):
        # Anführungszeichen und Klammern dürfen die FTS-Abfrage nicht zerlegen
        assert fts_expression('sonne" (strand)') == '"sonne"* AND "strand"*'

    def test_einzelne_buchstaben_werden_verworfen(self):
        # Ein-Zeichen-Tokens liefern nur Rauschen
        assert fts_expression("a b c") is None

    def test_leere_eingabe(self):
        assert fts_expression("") is None
        assert fts_expression("!") is None


class TestVolltext:
    def test_findet_dateinamen(self):
        clip_id = insert_clip("Rushes/Sonnenuntergang.mp4")
        assert clip_id in text_match_ids("sonnen")

    def test_findet_teilstueck_aus_zusammengesetztem_namen(self):
        clip_id = insert_clip("2026/2026-07-14_FX3_A7401.MP4")
        assert clip_id in text_match_ids("A7401")

    def test_findet_kamera(self):
        clip_id = insert_clip("a.mp4", camera_label="Sony FX3")
        assert clip_id in text_match_ids("FX3")

    def test_findet_tag(self):
        clip_id = insert_clip("a.mp4")
        conn = get_conn()
        tag_id = ensure_tag(conn, "Drohne", "source")
        conn.execute(
            "INSERT INTO clip_tags(clip_id, tag_id, source) VALUES (?, ?, 'manual')",
            (clip_id, tag_id),
        )
        reindex_fts(conn, clip_id)
        assert clip_id in text_match_ids("drohne")

    def test_findet_nichts_bei_unbekanntem_begriff(self):
        insert_clip("a.mp4")
        assert text_match_ids("giraffe") == []


class TestBuildWhere:
    def _ids(self, filters: ClipFilters) -> set[int]:
        where, params = build_where(filters)
        rows = get_conn().execute(f"SELECT c.id FROM clips c WHERE {where}", params).fetchall()
        return {row["id"] for row in rows}

    def test_versteckt_fehlende_dateien(self):
        vorhanden = insert_clip("a.mp4")
        insert_clip("b.mp4", status="missing")
        assert self._ids(ClipFilters()) == {vorhanden}

    def test_nur_fehlende(self):
        insert_clip("a.mp4")
        fehlend = insert_clip("b.mp4", status="missing")
        assert self._ids(ClipFilters(only_missing=True)) == {fehlend}

    def test_look_beruecksichtigt_manuelle_korrektur(self):
        auto = insert_clip("a.mp4", look="log")
        korrigiert = insert_clip("b.mp4", look="log", look_manual="graded")
        assert self._ids(ClipFilters(look="log")) == {auto}
        assert self._ids(ClipFilters(look="graded")) == {korrigiert}

    def test_ordner_mit_unterordnern(self):
        oben = insert_clip("Rushes/a.mp4")
        unten = insert_clip("Rushes/2026/b.mp4")
        insert_clip("Export/c.mp4")
        assert self._ids(ClipFilters(folder="Rushes")) == {oben, unten}

    def test_wurzelordner(self):
        wurzel = insert_clip("a.mp4")
        insert_clip("Rushes/b.mp4")
        assert self._ids(ClipFilters(folder="/")) == {wurzel}

    def test_dauer_bereich(self):
        kurz = insert_clip("a.mp4", duration=3.0)
        lang = insert_clip("b.mp4", duration=60.0)
        assert self._ids(ClipFilters(duration_max=10)) == {kurz}
        assert self._ids(ClipFilters(duration_min=10)) == {lang}

    def test_datum_bereich(self):
        alt = insert_clip("a.mp4", recorded_at="2025-01-05T10:00:00")
        neu = insert_clip("b.mp4", recorded_at="2026-07-14T10:00:00")
        assert self._ids(ClipFilters(date_from="2026-01-01")) == {neu}
        assert self._ids(ClipFilters(date_to="2025-12-31")) == {alt}

    def test_tags_oder_innerhalb_einer_kategorie(self):
        conn = get_conn()
        vier_k = insert_clip("a.mp4")
        hd = insert_clip("b.mp4")
        set_auto_tags(conn, vier_k, [("4K", "tech")])
        set_auto_tags(conn, hd, [("1080p", "tech")])
        assert self._ids(ClipFilters(tags=["4K", "1080p"])) == {vier_k, hd}

    def test_tags_und_zwischen_kategorien(self):
        conn = get_conn()
        treffer = insert_clip("a.mp4")
        daneben = insert_clip("b.mp4")
        set_auto_tags(conn, treffer, [("4K", "tech"), ("Sony FX3", "camera")])
        set_auto_tags(conn, daneben, [("4K", "tech"), ("DJI", "camera")])
        assert self._ids(ClipFilters(tags=["4K", "Sony FX3"])) == {treffer}

    def test_unbekanntes_tag_liefert_nichts(self):
        insert_clip("a.mp4")
        assert self._ids(ClipFilters(tags=["gibtsnicht"])) == set()


class TestFacetten:
    def test_zaehlt_tags_und_looks(self):
        conn = get_conn()
        erster = insert_clip("Rushes/a.mp4", look="log")
        zweiter = insert_clip("Rushes/b.mp4", look="graded")
        set_auto_tags(conn, erster, [("4K", "tech")])
        set_auto_tags(conn, zweiter, [("4K", "tech")])

        where, params = build_where(ClipFilters())
        result = facets(where, params)
        assert {"name": "4K", "count": 2} in result["tags"]["tech"]
        assert {"name": "log", "count": 1} in result["looks"]
        assert {"name": "Rushes", "count": 2} in result["folders"]
