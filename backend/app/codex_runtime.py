"""Persistente ChatGPT-Anmeldung und begrenzte Codex-Unterprozesse."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path

from .config import settings

_lock = threading.RLock()
_processes: set[subprocess.Popen] = set()
_login: subprocess.Popen | None = None
_login_state: dict = {"state": "idle", "url": None, "code": None, "error": None}
_status_cache: tuple[float, bool] = (0, False)
_auth_rejected = False
_stopping = False


def environment() -> dict[str, str]:
    settings.codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.codex_home.chmod(0o700)
    # Ein geerbter API-Key darf niemals unbemerkt statt des Abos benutzt werden.
    env = {k: v for k, v in os.environ.items() if k in {
        "PATH", "HOME", "LANG", "TZ", "SSL_CERT_FILE", "SSL_CERT_DIR",
        "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "NODE_EXTRA_CA_CERTS",
    }}
    env.update(CODEX_HOME=str(settings.codex_home), NO_COLOR="1", TERM="dumb")
    return env


def command() -> list[str]:
    return [settings.codex_path, "-c", 'cli_auth_credentials_store="file"',
            "-c", 'forced_login_method="chatgpt"']


def authenticated(refresh: bool = False) -> bool:
    global _status_cache
    with _lock:
        if _auth_rejected:
            return False
        if not refresh and time.monotonic() - _status_cache[0] < 15:
            return _status_cache[1]
        if not shutil.which(settings.codex_path):
            return False
        try:
            result = subprocess.run(command() + ["login", "status"], env=environment(),
                                    capture_output=True, text=True, timeout=10)
            ok = result.returncode == 0 and "chatgpt" in (result.stdout + result.stderr).lower()
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        _status_cache = (time.monotonic(), ok)
        return ok


def invalidate_auth(rejected: bool = False) -> None:
    global _status_cache, _auth_rejected
    with _lock:
        _status_cache = (0, False)
        if rejected:
            # login status prüft nur den lokalen Cache, nicht die Gültigkeit beim Dienst.
            _auth_rejected = True


def status() -> dict:
    ok = authenticated()
    with _lock:
        state = dict(_login_state)
    if ok:
        state.update(state="authenticated", url=None, code=None, error=None)
    elif _auth_rejected and state["state"] != "pending":
        state.update(state="error", error="Codex-Anmeldung abgelaufen. Bitte erneut mit ChatGPT anmelden.")
    return {**state, "installed": bool(shutil.which(settings.codex_path)), "authenticated": ok}


def terminate(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=3)
        except ProcessLookupError:
            pass


def spawn(args: list[str], **kwargs) -> subprocess.Popen:
    with _lock:
        if _stopping:
            raise RuntimeError("Codex wird beendet")
        proc = subprocess.Popen(args, env=environment(), start_new_session=True, **kwargs)
        _processes.add(proc)
        return proc


def forget(proc: subprocess.Popen) -> None:
    with _lock:
        _processes.discard(proc)


def start_login() -> dict:
    global _login, _login_state
    if authenticated(refresh=True):
        return status()
    with _lock:
        if _login is not None and _login.poll() is None:
            return status()
        if not shutil.which(settings.codex_path):
            raise ValueError("Codex CLI fehlt. Bitte das aktuelle Docker-Image installieren.")
        _login_state = {"state": "pending", "url": None, "code": None, "error": None}
        _login = spawn(command() + ["login", "--device-auth"], stdin=subprocess.DEVNULL,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        threading.Thread(target=_read_login, args=(_login,), name="codex-login", daemon=True).start()
    return status()


def _read_login(proc: subprocess.Popen) -> None:
    global _auth_rejected
    timer = threading.Timer(15 * 60, terminate, args=(proc,))
    timer.start()
    try:
        for raw in proc.stdout:
            line = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", raw)
            url = re.search(r"https://(?:auth\.openai\.com|chatgpt\.com)/[^\s\x1b]+", line)
            code = re.search(r"\b[A-Z0-9]{4,6}-[A-Z0-9]{4,6}\b", line)
            with _lock:
                if url:
                    _login_state["url"] = url.group(0)
                if code:
                    _login_state["code"] = code.group(0)
        result = proc.wait()
        if result == 0:
            with _lock:
                _auth_rejected = False
        invalidate_auth()
        with _lock:
            _login_state.update(state="authenticated" if result == 0 else "error", code=None, url=None,
                                error=None if result == 0 else "Anmeldung abgebrochen oder abgelaufen. Gerätecode-Login im ChatGPT-Konto aktivieren und erneut versuchen.")
    finally:
        timer.cancel()
        proc.stdout.close()
        forget(proc)


def run_analysis(args: list[str], prompt: str, cwd: Path) -> tuple[int, str]:
    # Ausgaben bleiben lokal und werden nicht als ungefiltertes CLI-Protokoll veröffentlicht.
    import tempfile

    with tempfile.TemporaryFile(mode="w+") as output:
        proc = spawn(args, cwd=cwd, stdin=subprocess.PIPE, stdout=output, stderr=output, text=True)
        try:
            proc.communicate(prompt, timeout=settings.analysis_timeout)
            output.seek(0, 2)
            size = output.tell()
            output.seek(max(0, size - 12000))
            return proc.returncode, output.read()
        except subprocess.TimeoutExpired:
            terminate(proc)
            raise RuntimeError("Zeitlimit für Codex-Analyse überschritten") from None
        finally:
            terminate(proc)
            forget(proc)


def start() -> None:
    global _stopping
    with _lock:
        _stopping = False
    invalidate_auth()


def stop() -> None:
    global _stopping
    with _lock:
        _stopping = True
        processes = list(_processes)
    for proc in processes:
        terminate(proc)
