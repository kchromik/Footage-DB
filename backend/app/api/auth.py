from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from ..config import settings
from .deps import auth_disabled, clear_session, current_user, issue_session, verify_credentials

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Sehr einfache Bremse gegen Durchprobieren von Passwoertern
_failures: dict[str, list[float]] = {}
MAX_FAILURES = 8
WINDOW = 300.0


class LoginRequest(BaseModel):
    username: str
    password: str


def _too_many_failures(key: str) -> bool:
    now = time.time()
    attempts = [t for t in _failures.get(key, []) if now - t < WINDOW]
    _failures[key] = attempts
    return len(attempts) >= MAX_FAILURES


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict:
    client = request.client.host if request.client else "unbekannt"
    if _too_many_failures(client):
        raise HTTPException(
            status_code=429, detail="Zu viele Fehlversuche, bitte kurz warten"
        )

    if not verify_credentials(payload.username, payload.password):
        _failures.setdefault(client, []).append(time.time())
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort falsch")

    _failures.pop(client, None)
    secure = request.url.scheme == "https" or request.headers.get(
        "x-forwarded-proto"
    ) == "https"
    issue_session(response, payload.username, secure=secure)
    return {"user": payload.username}


@router.post("/logout")
def logout(response: Response) -> dict:
    clear_session(response)
    return {"ok": True}


@router.get("/me")
def me(request: Request) -> dict:
    return {
        "user": current_user(request),
        "auth_required": not auth_disabled(),
        "app": "FootageDB",
        "media_root": str(settings.media_root),
    }
