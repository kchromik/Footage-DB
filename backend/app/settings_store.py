"""Einstellungen, die zur Laufzeit änderbar sind.

Die `.env` liefert die Startwerte. Was über den Einrichtungsassistenten oder
die Einstellungsseite geändert wird, landet in der Tabelle `settings` und
gewinnt danach gegen die Umgebungsvariable. So muss für eine Anpassung nicht
der Container neu gebaut werden.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
from typing import Any

from .config import settings
from .db import get_conn

log = logging.getLogger(__name__)

# key -> (Typ, Standard aus der .env)
FIELDS: dict[str, tuple[type, Any]] = {
    "auth_user": (str, None),
    "proxy_height": (int, None),
    "proxy_crf": (int, None),
    "hwaccel": (str, None),
    "semantic_enabled": (bool, None),
    "organize_uploads": (bool, None),
    "organize_pattern": (str, None),
    "worker_count": (int, None),
    "rescan_interval_minutes": (int, None),
}

SETUP_DONE = "setup_complete"
PASSWORD_HASH = "auth_password_hash"


def _env_default(key: str) -> Any:
    if key == "organize_pattern":
        return settings.pattern
    return getattr(settings, key, None)


class RuntimeSettings:
    """Zwischenspeicher über der settings-Tabelle."""

    def __init__(self) -> None:
        self._cache: dict[str, Any] = {}
        self._loaded = False
        self._lock = threading.Lock()

    def reload(self) -> None:
        with self._lock:
            rows = get_conn().execute("SELECT key, value FROM settings").fetchall()
            self._cache = {row["key"]: row["value"] for row in rows}
            self._loaded = True

    def _raw(self, key: str) -> str | None:
        if not self._loaded:
            self.reload()
        return self._cache.get(key)

    def get(self, key: str) -> Any:
        kind, _ = FIELDS.get(key, (str, None))
        raw = self._raw(key)
        if raw is None:
            return _env_default(key)
        try:
            if kind is bool:
                return raw.lower() in {"1", "true", "yes", "on"}
            if kind is int:
                return int(raw)
            return raw
        except (TypeError, ValueError):
            return _env_default(key)

    def set_many(self, values: dict[str, Any]) -> None:
        conn = get_conn()
        for key, value in values.items():
            if isinstance(value, bool):
                value = "true" if value else "false"
            conn.execute(
                "INSERT INTO settings(key, value, updated_at) "
                "VALUES (?, ?, datetime('now')) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (key, str(value)),
            )
        self.reload()

    # --- bequeme Zugriffe -------------------------------------------

    @property
    def auth_user(self) -> str:
        return self.get("auth_user") or settings.auth_user

    @property
    def proxy_height(self) -> int:
        return int(self.get("proxy_height") or settings.proxy_height)

    @property
    def proxy_crf(self) -> int:
        return int(self.get("proxy_crf") or settings.proxy_crf)

    @property
    def hwaccel(self) -> str:
        return self.get("hwaccel") or settings.hwaccel

    @property
    def semantic_enabled(self) -> bool:
        return bool(self.get("semantic_enabled"))

    @property
    def organize_uploads(self) -> bool:
        return bool(self.get("organize_uploads"))

    @property
    def organize_pattern(self) -> str:
        value = self.get("organize_pattern")
        return value.strip() if isinstance(value, str) and value.strip() else settings.pattern

    @property
    def worker_count(self) -> int:
        return max(1, int(self.get("worker_count") or settings.worker_count))

    @property
    def rescan_interval_minutes(self) -> int:
        value = self.get("rescan_interval_minutes")
        return int(value) if value is not None else settings.rescan_interval_minutes

    # --- Einrichtung ------------------------------------------------

    @property
    def setup_complete(self) -> bool:
        return (self._raw(SETUP_DONE) or "").lower() in {"1", "true", "yes"}

    def mark_setup_complete(self) -> None:
        self.set_many({SETUP_DONE: "true"})

    @property
    def password_hash(self) -> str | None:
        return self._raw(PASSWORD_HASH)

    def set_password(self, password: str) -> None:
        self.set_many({PASSWORD_HASH: hash_password(password)})

    def clear_password(self) -> None:
        get_conn().execute("DELETE FROM settings WHERE key = ?", (PASSWORD_HASH,))
        self.reload()

    @property
    def has_password(self) -> bool:
        """Ist überhaupt irgendwo ein Passwort hinterlegt?"""
        return bool(self.password_hash) or bool(settings.auth_password.strip())


# --- Passwörter --------------------------------------------------------

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_hex, digest_hex = stored.split("$")
        if scheme != "scrypt":
            return False
        digest = hashlib.scrypt(
            password.encode("utf-8"),
            salt=bytes.fromhex(salt_hex),
            n=int(n),
            r=int(r),
            p=int(p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), digest_hex)


runtime = RuntimeSettings()
