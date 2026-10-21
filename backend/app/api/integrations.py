"""Verwaltung von Codex-Anmeldung und lesendem MCP-Zugang in der Oberfläche."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from .. import analysis, codex_runtime, mcp_server
from ..db import get_conn
from ..settings_store import runtime
from .deps import auth_disabled, require_user


def require_admin(request: Request):
    if auth_disabled():
        raise HTTPException(403, "Bitte zuerst ein Passwort für FootageDB einrichten.")
    return require_user(request)


router = APIRouter(prefix="/api/integrations", tags=["integrations"], dependencies=[Depends(require_admin)])


@router.get("")
def status(request: Request, response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"codex": codex_runtime.status(), "analysis": analysis.status(),
            "mcp": {"url": mcp_server.public_base(request) + "/mcp/", "read_only": True,
                    "transport": "Streamable HTTP", "token_configured": True}}


@router.post("/codex/login")
def login(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        analysis.resume()
        return codex_runtime.start_login()
    except (ValueError, OSError) as exc:
        raise HTTPException(400, str(exc)) from None


class AnalysisSettings(BaseModel):
    enabled: bool


@router.patch("/analysis")
def configure(payload: AnalysisSettings) -> dict:
    runtime.set_many({"analysis_enabled": payload.enabled})
    if payload.enabled:
        analysis.resume()
    return analysis.status()


@router.post("/analysis/retry")
def retry() -> dict:
    conn = get_conn()
    changed = conn.execute("UPDATE jobs SET state='queued',attempts=0,error=NULL,available_at=0 "
                           "WHERE id IN (SELECT MAX(id) FROM jobs WHERE type='analyze' AND state='failed' GROUP BY clip_id) "
                           "AND NOT EXISTS (SELECT 1 FROM jobs j WHERE j.clip_id=jobs.clip_id "
                           "AND j.type='analyze' AND j.state IN ('queued','running'))").rowcount
    conn.execute("UPDATE clips SET analysis_status='pending' WHERE analysis_status='failed'")
    analysis.resume()
    return {"requeued": changed, "backfilled": analysis.backfill()}


@router.post("/mcp/token")
def show_token(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"token": mcp_server.access_token()}


@router.post("/mcp/token/rotate")
def rotate_token(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    return {"token": mcp_server.rotate_token()}
