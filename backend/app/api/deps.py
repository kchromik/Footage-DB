"""Anmeldung per signiertem Session-Cookie.

Das Passwort kann aus zwei Quellen kommen: aus der `.env` oder aus dem
Einrichtungsassistenten (dann liegt es als scrypt-Hash in der Datenbank).
Der Hash aus der Datenbank hat Vorrang. Ist beides leer, läuft die Oberfläche
ohne Anmeldung, das ist nur für ein abgeschottetes Heimnetz gedacht.
"""

from __future__ import annotations

import hmac
import logging
import secrets

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..config import settings
from ..settings_store import runtime, verify_password

log = logging.getLogger(__name__)

COOKIE_NAME = "fdb_session"

_secret = settings.secret_key.strip()
if not _secret:
    _secret = secrets.token_hex(32)
    log.warning(
        "FDB_SECRET_KEY ist nicht gesetzt. Es wird ein Zufallsschlüssel verwendet, "
        "dadurch werden alle Anmeldungen bei jedem Neustart ungültig."
    )

_serializer = URLSafeTimedSerializer(_secret, salt="fdb-session")


def auth_disabled() -> bool:
    """Wahr, solange nirgends ein Passwort hinterlegt ist."""
    try:
        return not runtime.has_password
    except Exception:  # noqa: BLE001 - vor der Datenbank-Initialisierung
        return not settings.auth_password.strip()


def verify_credentials(username: str, password: str) -> bool:
    expected_user = runtime.auth_user.strip()
    if not hmac.compare_digest(username.strip(), expected_user):
        return False

    stored = runtime.password_hash
    if stored:
        return verify_password(password, stored)
    if settings.auth_password:
        return hmac.compare_digest(password, settings.auth_password)
    return False


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
    if auth_disabled():
        return runtime.auth_user or "lokal"
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
