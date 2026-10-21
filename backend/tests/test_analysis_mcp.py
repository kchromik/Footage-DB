"""Analyse-Lebenszyklus, MCP-Protokoll und getrennte Leseberechtigungen."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import analysis, codex_runtime, jobs, library, mcp_server
from app.config import settings
from app.db import get_conn, init_db, reindex_fts
from app.settings_store import runtime
from conftest import make_clip, needs_ffmpeg


@pytest.fixture
def clip(media_root):
    path = media_root / "broll.mp4"
    path.write_bytes(b"original-video-content")
    stat = path.stat()
    conn = get_conn()
    cid = conn.execute("INSERT INTO clips(path,filename,status,size_bytes,mtime,duration,width,height) "
                       "VALUES ('broll.mp4','broll.mp4','indexed',?,?,20,1920,1080)",
                       (stat.st_size, stat.st_mtime)).lastrowid
    reindex_fts(conn, cid)
    return conn.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()


@pytest.fixture
def client(media_root, monkeypatch):
    from app.main import app

    monkeypatch.setattr(codex_runtime, "authenticated", lambda **kw: False)
    with TestClient(app) as client:
        assert client.post("/api/auth/login", json={"username": "tester", "password": "geheim"}).status_code == 200
        yield client


def result_for(frames):
    return analysis.ClipAnalysis(
        summary="A quiet coastal landscape with a lighthouse.", summary_de="Ruhige Küste mit Leuchtturm.",
        tags=["coast", "lighthouse"], tags_de=["Küste", "Leuchtturm"], subjects=["lighthouse"],
        actions=[], setting="coast", shot_type="wide", camera_motion="unknown", lighting="daylight",
        mood=["calm"], visible_text=[], caveats=["Sampled frames only"],
        frame_notes=[analysis.FrameNote(frame_index=f["index"], description="Coast") for f in frames],
    )


def fake_frames(clip, directory):
    from PIL import Image

    path = directory / "frame.jpg"
    Image.new("RGB", (64, 36), "blue").save(path)
    return [{"index": 0, "timestamp_seconds": 1.0, "path": path}]


def run_mock_analysis(monkeypatch, clip, callback=None):
    monkeypatch.setattr(analysis, "can_analyze", lambda: True)
    monkeypatch.setattr(analysis, "extract_frames", fake_frames)
    monkeypatch.setattr(analysis, "analyze", callback or (lambda c, frames, directory: result_for(frames)))
    analysis._stop.clear()
    jobs.enqueue("analyze", clip["id"])
    job = jobs._claim_job(analysis=True)
    assert job is not None
    return job


def test_bestand_backfill_ist_idempotent(clip):
    assert analysis.backfill() == 1
    assert analysis.backfill() == 0
    assert jobs._claim_job() is None  # Allgemeine Worker fassen Codex-Jobs nicht an.
    assert jobs._claim_job(analysis=True)["clip_id"] == clip["id"]


def test_analyse_speichert_frames_tags_fts_und_erhaelt_manuelle_tags(clip, monkeypatch):
    conn = get_conn()
    tag = library.ensure_tag(conn, "coast")
    conn.execute("INSERT INTO clip_tags VALUES (?,?,'manual')", (clip["id"], tag))
    job = run_mock_analysis(monkeypatch, clip)
    analysis.job_analyze(job)
    ai = analysis.get_analysis(clip["id"])
    assert ai["content"]["summary_de"].startswith("Ruhige")
    assert ai["audio_analyzed"] is False
    assert mcp_server.frame_path(clip["id"], 0).exists()
    assert conn.execute("SELECT source FROM clip_tags WHERE clip_id=? AND tag_id=?", (clip["id"], tag)).fetchone()[0] == "manual"
    assert conn.execute("SELECT clip_id FROM clips_fts WHERE clips_fts MATCH 'Leuchtturm'").fetchone()[0] == clip["id"]
    monkeypatch.setattr(analysis, "analyze", lambda *a: pytest.fail("Erfolgreiche Datei erneut analysiert"))
    analysis.job_analyze(job)


def test_geaenderte_datei_verwirft_laufendes_ergebnis(clip, monkeypatch):
    def change_source(c, frames, directory):
        (settings.media_root / c["path"]).write_bytes(b"changed source during analysis")
        return result_for(frames)
    job = run_mock_analysis(monkeypatch, clip, change_source)
    with pytest.raises(jobs.DeferredJob):
        analysis.job_analyze(job)
    assert analysis.get_analysis(clip["id"]) is None


def test_austausch_loescht_alte_ki_tags_und_analyse(clip, monkeypatch):
    analysis.job_analyze(run_mock_analysis(monkeypatch, clip))
    source = settings.media_root / clip["path"]
    source.write_bytes(b"new source with a different size")
    library.upsert_scanned_file(clip["path"], source.stat())
    conn = get_conn()
    assert analysis.get_analysis(clip["id"]) is None
    assert conn.execute("SELECT COUNT(*) FROM clip_tags WHERE source='ai'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM clips_fts WHERE clips_fts MATCH 'Leuchtturm'").fetchone()[0] == 0


def test_quota_pause_hat_keine_verlorenen_jobs(clip, monkeypatch):
    job = run_mock_analysis(monkeypatch, clip)
    monkeypatch.setitem(jobs._HANDLERS, "analyze", (lambda j: (_ for _ in ()).throw(jobs.DeferredJob("Kontingent", 1800)), 60))
    jobs.WorkerPool(1, analysis=True)._run_job(job)
    row = get_conn().execute("SELECT * FROM jobs WHERE id=?", (job["id"],)).fetchone()
    assert row["state"] == "queued" and row["attempts"] == 0
    assert row["available_at"] > time.time() + 1700
    assert jobs._claim_job(analysis=True) is None


def test_gleich_grosse_dateiaenderung_innerhalb_einer_sekunde(clip):
    source = settings.media_root / clip["path"]
    source.write_bytes(b"x" * clip["size_bytes"])
    os.utime(source, (clip["mtime"] + 0.25, clip["mtime"] + 0.25))
    _, action = library.upsert_scanned_file(clip["path"], source.stat())
    assert action == "updated"


def test_neustart_erhaelt_warteschlange_und_ergebnis(clip, monkeypatch):
    job = run_mock_analysis(monkeypatch, clip)
    init_db()
    assert get_conn().execute("SELECT state FROM jobs WHERE id=?", (job["id"],)).fetchone()[0] == "queued"
    analysis.job_analyze(job)
    init_db()
    assert analysis.get_analysis(clip["id"])["schema_version"] == analysis.SCHEMA_VERSION


@needs_ffmpeg
def test_echte_frame_extraktion(media_root, tmp_path):
    source = make_clip(media_root / "echter-clip.mp4", seconds=1)
    cid, _ = library.upsert_scanned_file(source.name, source.stat())
    conn = get_conn()
    conn.execute("UPDATE clips SET duration=1,status='indexed' WHERE id=?", (cid,))
    clip = conn.execute("SELECT * FROM clips WHERE id=?", (cid,)).fetchone()
    analysis._stop.clear()
    frames = analysis.extract_frames(clip, tmp_path)
    assert len(frames) == 3
    assert all(f["path"].stat().st_size > 100 for f in frames)
    assert all(0 <= f["timestamp_seconds"] < 1 for f in frames)


def rpc(client, token, method, params=None):
    return client.post("/mcp/", headers={"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream", "MCP-Protocol-Version": "2025-11-25"},
                       json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


def test_mcp_protokoll_lesend_download_und_berechtigungen(client, media_root):
    # Erst nach Client-Start anlegen, damit dessen Fixture die Datei nicht entfernt.
    source = media_root / "original.mp4"
    source.write_bytes(b"0123456789-original")
    cid, _ = library.upsert_scanned_file(source.name, source.stat())
    get_conn().execute("UPDATE clips SET status='indexed' WHERE id=?", (cid,))
    token = client.post("/api/integrations/mcp/token").json()["token"]
    assert client.post("/mcp/", json={}).status_code == 401  # Session-Cookie reicht nicht.
    response = rpc(client, token, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}})
    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "FootageDB"
    tools = rpc(client, token, "tools/list").json()["result"]["tools"]
    assert {t["name"] for t in tools} == {"search_clips", "get_clip", "get_frame", "get_download", "list_library"}
    assert all(t["annotations"]["readOnlyHint"] for t in tools)
    search = rpc(client, token, "tools/call", {"name": "search_clips", "arguments": {"query": "original"}}).json()["result"]
    assert not search.get("isError")
    assert search["structuredContent"]["items"][0]["id"] == cid
    result = rpc(client, token, "tools/call", {"name": "get_download", "arguments": {"clip_id": cid}}).json()["result"]
    link = result["structuredContent"]["url"]
    client.cookies.clear()
    assert client.get(link).content == source.read_bytes()
    part = client.get(link, headers={"Range": "bytes=2-5"})
    assert part.status_code == 206 and part.content == b"2345"
    assert client.get(link, headers={"Range": "bytes=5-2"}).status_code == 416
    assert client.head(link).headers["content-length"] == str(source.stat().st_size)
    assert client.get(link.replace("/original?", "/poster?")).status_code == 401
    assert client.get("/api/integrations", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    assert client.patch(f"/api/clips/{cid}", json={"notes": "no"}, headers={"Authorization": f"Bearer {token}"}).status_code == 401
    mcp_server.rotate_token()
    assert client.get(link).status_code == 401
    assert rpc(client, token, "tools/list").status_code == 401


def test_mcp_origin_pruefung_und_anonyme_verwaltung(client):
    token = mcp_server.access_token()
    response = client.post("/mcp/", headers={"Authorization": f"Bearer {token}", "Origin": "https://fremde-seite.test"}, json={})
    assert response.status_code == 403
    client.cookies.clear()
    assert client.post("/api/integrations/codex/login").status_code == 401
    assert client.post("/api/integrations/mcp/token").status_code == 401


def test_abgelaufene_links_werden_abgelehnt(client, media_root, monkeypatch):
    path = media_root / "alt.mp4"
    path.write_bytes(b"original")
    cid, _ = library.upsert_scanned_file(path.name, path.stat())
    link = mcp_server.media_url(cid, "original")
    monkeypatch.setattr(mcp_server, "LINK_TTL", -1)
    assert client.get(link).status_code == 401


def test_codex_umgebung_verwendet_keinen_api_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "darf-nicht-vererbt-werden")
    monkeypatch.setenv("CODEX_API_KEY", "auch-nicht")
    env = codex_runtime.environment()
    assert "OPENAI_API_KEY" not in env and "CODEX_API_KEY" not in env
    assert env["CODEX_HOME"] == str(settings.data_dir / "codex")


def test_abgelaufene_anmeldung_bleibt_trotz_lokalem_cache_gesperrt(monkeypatch):
    monkeypatch.setattr(codex_runtime, "_auth_rejected", False)
    monkeypatch.setattr(codex_runtime, "_status_cache", (time.monotonic(), True))
    monkeypatch.setattr(codex_runtime, "_login_state", {"state": "idle", "code": None, "url": None, "error": None})
    codex_runtime.invalidate_auth(rejected=True)
    assert not codex_runtime.authenticated(refresh=True)
    assert codex_runtime.status()["state"] == "error"


def test_codex_aufruf_validiert_bildreferenzen_und_kein_shellzugriff(clip, tmp_path, monkeypatch):
    frames = fake_frames(clip, tmp_path)
    def run(args, prompt, directory):
        assert "--sandbox" in args and args[args.index("--sandbox") + 1] == "read-only"
        assert "features.shell_tool=false" in args
        assert "--image" in args and "--output-schema" in args
        data = result_for(frames).model_dump()
        data["frame_notes"][0]["frame_index"] = 23
        (directory / "result.json").write_text(json.dumps(data))
        return 0, ""
    monkeypatch.setattr(codex_runtime, "run_analysis", run)
    with pytest.raises(ValueError, match="Bildreferenzen"):
        analysis.analyze(clip, frames, tmp_path)
