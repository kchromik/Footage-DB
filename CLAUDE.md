# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Projekt

FootageDB: selbstgehostete B-Roll-Bibliothek für das eigene NAS. Ein Container, keine externen Dienste. Stack: FastAPI + SQLite (Backend), React 18 + Vite (Frontend). Indexiert einen Footage-Ordner, erzeugt Poster/Sprites/Previews per ffmpeg, Metadaten aus ffprobe/exiftool/Sony-Sidecars, inhaltliche Suche über ein lokales CLIP-Modell (ONNX, CPU).

## Befehle

```bash
# Backend-Entwicklung (Port 8099, das Frontend-Dev-Proxy erwartet diesen Port)
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
FDB_MEDIA_ROOT=./testmedia FDB_DATA_DIR=./data \
  PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --reload --port 8099

# Frontend-Entwicklung (Port 5173, leitet /api an 8099 weiter)
cd frontend && npm install && npm run dev

# Tests (brauchen ffmpeg und exiftool im PATH)
cd backend && ../.venv/bin/python -m pytest
cd backend && ../.venv/bin/python -m pytest tests/test_api.py            # eine Datei
cd backend && ../.venv/bin/python -m pytest tests/test_api.py -k upload  # ein Test

# Frontend-Typprüfung und Build (tsc läuft im Build mit)
cd frontend && npm run build

# Komplettes Image lokal
docker compose up -d --build
```

API-Dokumentation läuft unter `/api/docs`. Die Tests in `backend/tests/conftest.py` setzen alle nötigen Umgebungsvariablen selbst (temporäre Ordner, Semantik aus, Worker aus) und müssen vor dem App-Import stehen.

## Architektur

Ein Prozess, ein Container: FastAPI liefert die gebaute React-Oberfläche als statische Dateien aus (`main.py`, SPA-Fallback im 404-Handler: API-Pfade bekommen JSON, alles andere `index.html`).

**SQLite ist der einzige Speicher.** Datenbank, Volltextindex (FTS), Job-Warteschlange und Laufzeit-Einstellungen liegen alle in einer SQLite-Datei (WAL-Modus, eine Verbindung pro Thread, siehe `db.py`). Kein Redis, kein Celery, keine Vektordatenbank.

**Verarbeitungskette** (`tasks.py`): Jobs laufen in der Reihenfolge `probe → poster → proxy → sprite → embed`, priorisiert über `jobs.py` (Warteschlange in SQLite, Worker sind Threads, die eigentliche Arbeit passiert in ffmpeg-Unterprozessen). Material, das jeder Browser direkt abspielt (h264, ≤1080p, ≤14 Mbit/s), bekommt keinen Proxy.

**Einstellungen zweistufig** (`config.py` + `settings_store.py`): Die `.env` (Präfix `FDB_`, pydantic-settings) liefert Startwerte. Was über den Einrichtungsassistenten oder die Einstellungsseite geändert wird, landet in der Tabelle `settings` und gewinnt danach gegen die Umgebungsvariable. Neuer Code, der Einstellungen liest, muss `runtime` aus `settings_store.py` nutzen, nicht direkt `settings`, wenn der Wert zur Laufzeit änderbar sein soll.

**Scanner** (`scanner.py`): Verzeichnisdurchlauf plus watchdog-Dateiüberwachung plus periodischer Rescan. Vor abgeschlossener Einrichtung startet kein automatischer Scan (der Assistent stößt den ersten Scan selbst an).

**Live-Updates** (`events.py`): Ein thread-sicherer EventBus publiziert von Worker-Threads in den asyncio-Loop, die Oberfläche hängt per Server-Sent Events dran (`frontend/src/lib/useEvents.ts`). Der Vite-Dev-Proxy hat dafür eine SSE-Sonderbehandlung.

**Suche** (`search/`): `query.py` baut die SQL-Abfrage. Wichtiges Prinzip: alle Facetten (Kamera, Auflösung, Bildrate, Look, Herkunft) sind automatisch vergebene Tags, es gibt nur einen Filtermechanismus. Die semantische Suche (`semantic.py`) hält den Vektorindex als numpy-Matrix im RAM.

**Metadaten-Heuristiken** (`metadata/rules.py`): Kamera-Aliasse, Look-Erkennung (LOG/graded/HDR/Rec.709) und Auto-Tags stehen bewusst alle in dieser einen Datei. Ein manuell gesetzter Look gewinnt immer gegen die Automatik.

**Einsortieren** (`organize.py`): Immer zweistufig, erst Plan, dann Ausführung, jede Bewegung landet in der Tabelle `moves` und ist als ganzer Stapel rückgängig machbar.

**Auth** (`api/deps.py`): Signiertes Session-Cookie. Passwort aus `.env` oder als scrypt-Hash aus der Datenbank (Datenbank hat Vorrang). Ohne Passwort läuft die Oberfläche offen.

**Frontend**: Kein Router, kein State-Management-Framework. `App.tsx` hält den View-State, `lib/api.ts` ist ein schlanker fetch-Wrapper, Komponenten liegen flach in `components/`.

## Konventionen

- Docstrings, Kommentare, Log-Meldungen und Commit-Messages sind auf Deutsch. Commits folgen Conventional Commits (`feat:`, `fix:`) mit deutscher Beschreibung.
- Kommentare erklären das Warum (z. B. warum kein Celery, warum Unterordner zu je 500 Dateien), nicht das Was. Diesen Stil beibehalten.
- Abgeleitete Dateien (Poster, Sprites, Proxies) immer über `paths.py` adressieren, dort steckt das Sharding.
