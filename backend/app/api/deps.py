"""Anmeldung per signiertem Session-Cookie."""

from __future__ import annotations

import hmac
import logging
import secrets

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import settings

log = logging.getLogger(__name__)

COOKIE_NAME = "fdb_session"

_secret = settings.secret_key.strip()
if not _secret:
    _secret = secrets.token_hex(32)
    log.warning(
        "FDB_SECRET_KEY ist nicht gesetzt. Es wird ein Zufallsschluessel verwendet, "
        "dadurch werden alle Anmeldungen bei jedem Neustart ungueltig."
    )

_serializer = URLSafeTimedSerializer(_secret, salt="fdb-session")

# Ohne gesetztes Passwort laeuft die App ohne Anmeldung (nur fuer den
# abgeschotteten Heimnetz-Betrieb gedacht).
AUTH_DISABLED = not settings.auth_password.strip()
if AUTH_DISABLED:
    log.warning(
        "FDB_AUTH_PASSWORD ist leer: die Oberflaeche ist ohne Anmeldung erreichbar."
    )


def verify_credentials(username: str, password: str) -> bool:
    user_ok = hmac.compare_digest(username.strip(), settings.auth_user.strip())
    pass_ok = hmac.compare_digest(password, settings.auth_password)
    return user_ok and pass_ok


def issue_session(response: Response, username: str, secure: bool = False) -> None:
    token = _serializer.dumps({"u": username})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def current_user(request: Request) -> str | None:
    if AUTH_DISABLED:
        return settings.auth_user or "lokal"
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=settings.session_max_age)
    except (BadSignature, SignatureExpired):
        return None
    return data.get("u")


def require_user(request: Request) -> str:
    user = current_user(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Nicht angemeldet"
        )
    return user
