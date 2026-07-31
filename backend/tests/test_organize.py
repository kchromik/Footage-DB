"""Tests für das Einsortieren: Zielpfade, Kollisionen, Ausführung, Undo."""

from __future__ import annotations

from datetime import datetime

from app import organize
from app.db import get_conn

from helpers import insert_clip


class TestZielpfad:
    def test_schema_jahr_monat_kamera(self):
        target = organize.target_directory("2026-07-14T10:00:00", "2026-01-01", "Sony FX3")
        assert target == "2026/2026-07/Sony-FX3"

    def test_ohne_kamera(self):
        target = organize.target_directory("2026-07-14T10:00:00", "2026-01-01", None)
        assert target == "2026/2026-07/Unbekannte-Kamera"

    def test_faellt_auf_anlagedatum_zurueck(self):
        target = organize.target_directory(None, "2025-03-02 08:00:00", "DJI")
        assert target.startswith("2025/2025-03/")

    def test_neue_datei(self):
        path = organize.target_for_new_file("Clip.MP4", datetime(2026, 5, 4), "Sony FX3")
        assert path == "2026/2026-05/Sony-FX3/Clip.MP4"


class TestUniqueTarget:
    def test_freier_name_bleibt(self, media_root):
        assert organize.unique_target("2026", "a.mp4", set()) == "2026/a.mp4"

    def test_weicht_bestehender_datei_aus(self, media_root):
        (media_root / "2026").mkdir(parents=True)
        (media_root / "2026" / "a.mp4").write_bytes(b"x")
        assert organize.unique_target("2026", "a.mp4", set()) == "2026/a_2.mp4"

    def test_weicht_geplantem_namen_aus(self, media_root):
        assert organize.unique_target("2026", "a.mp4", {"2026/a.mp4"}) == "2026/a_2.mp4"

    def test_wurzelordner(self, media_root):
        assert organize.unique_target("", "a.mp4", set()) == "a.mp4"


class TestPlanUndAusfuehrung:
    def _datei(self, media_root, relative: str) -> None:
        path = media_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"video")

    def test_plan_ueberspringt_bereits_sortierte(self, media_root):
        self._datei(media_root, "2026/2026-07/Sony-FX3/a.mp4")
        insert_clip(
            "2026/2026-07/Sony-FX3/a.mp4",
            camera_label="Sony FX3",
            recorded_at="2026-07-14T10:00:00",
        )
        plan = organize.plan()
        assert plan.moves == []
        assert plan.already_sorted == 1

    def test_plan_ignoriert_noch_nicht_eingelesene(self, media_root):
        self._datei(media_root, "neu.mp4")
        insert_clip("neu.mp4", status="new")
        plan = organize.plan()
        assert plan.moves == []
        assert any("eingelesen" in entry["reason"] for entry in plan.skipped)

    def test_ausfuehren_und_zuruecknehmen(self, media_root):
        self._datei(media_root, "Rushes/a.mp4")
        clip_id = insert_clip(
            "Rushes/a.mp4", camera_label="DJI", recorded_at="2026-03-09T12:00:00"
        )

        plan = organize.plan()
        assert len(plan.moves) == 1
        assert plan.moves[0].to_path == "2026/2026-03/DJI/a.mp4"

        result = organize.apply(plan.moves)
        assert result["moved"] == 1
        assert (media_root / "2026/2026-03/DJI/a.mp4").exists()
        assert not (media_root / "Rushes/a.mp4").exists()

        row = get_conn().execute("SELECT path, folder FROM clips WHERE id=?", (clip_id,)).fetchone()
        assert row["path"] == "2026/2026-03/DJI/a.mp4"
        assert row["folder"] == "2026/2026-03/DJI"

        undo = organize.undo(result["batch"])
        assert undo["reverted"] == 1
        assert (media_root / "Rushes/a.mp4").exists()
        row = get_conn().execute("SELECT path FROM clips WHERE id=?", (clip_id,)).fetchone()
        assert row["path"] == "Rushes/a.mp4"

    def test_leere_ordner_werden_entfernt(self, media_root):
        self._datei(media_root, "Alt/a.mp4")
        insert_clip("Alt/a.mp4", camera_label="Sony", recorded_at="2026-03-09T12:00:00")
        organize.apply(organize.plan().moves)
        assert not (media_root / "Alt").exists()

    def test_medienordner_selbst_bleibt(self, media_root):
        organize.prune_empty_dirs({media_root})
        assert media_root.exists()

    def test_fehlende_quelldatei_wird_gemeldet(self, media_root):
        insert_clip("weg.mp4", camera_label="Sony", recorded_at="2026-03-09T12:00:00")
        plan = organize.plan()
        assert plan.moves == []
        assert any(entry.get("reason") == "Datei fehlt" for entry in plan.skipped)
