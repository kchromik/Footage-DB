# FootageDB

Selbstgehostete B-Roll-Bibliothek fuer das eigene NAS. Indexiert einen
Footage-Ordner, erzeugt Vorschaubilder und abspielbare Previews und macht den
ganzen Bestand ueber eine Weboberflaeche durchsuchbar.

- Vorschau beim Drueberfahren, ohne dass Video geladen wird
- Wiedergabe im Browser auch bei HEVC, 10 Bit, HDR oder 4K
- Metadaten aus ffprobe, exiftool und Sony-XML-Sidecars
- Erkennt automatisch LOG, graded, HDR oder Rec.709
- Suche nach Bildinhalt ueber ein lokales CLIP-Modell, ohne Cloud
- Upload grosser Dateien blockweise, mit Wiederaufnahme nach Abbruch
- Einsortieren nach Jahr, Monat und Kamera, mit Vorschau und Undo

Stack: FastAPI, SQLite, React. Ein Container, keine externen Dienste.

## Start

```bash
cp .env.example .env
docker compose up -d --build
```

In der `.env` mindestens setzen:

```ini
FDB_MEDIA_PATH=/volume1/BRoll        # dein Footage-Ordner auf dem NAS
FDB_AUTH_PASSWORD=ein-gutes-passwort
FDB_SECRET_KEY=<openssl rand -hex 32>
PUID=1000                            # id -u
PGID=1000                            # id -g
```

Oberflaeche: `http://<nas-ip>:8080`

Beim ersten Start wird der Medienordner eingelesen, danach entstehen im
Hintergrund Vorschaubilder, Previews und die Bildanalyse. Die Kacheln fuellen
sich waehrenddessen nach und nach. Fuer die inhaltliche Suche werden einmalig
rund 600 MB Modelldaten geladen.

## Volumes

| Ort | Inhalt |
|---|---|
| `FDB_MEDIA_PATH` | deine Videodateien, beliebig verschachtelt |
| `FDB_DATA_PATH` | Datenbank, Vorschaubilder, Previews, CLIP-Modell |

Im Footage-Ordner landet nichts ausser den Dateien selbst. Sichern lohnt sich
vor allem `footagedb.sqlite3`, dort stecken die selbst vergebenen Tags und
Notizen. Alles andere baut ein neuer Scan wieder auf.

## Hardware-Encoding

Bei Intel-CPUs mit iGPU in der `docker-compose.yml` einkommentieren:

```yaml
devices:
  - /dev/dri:/dev/dri
```

Die App testet beim Start selbst, ob VAAPI nutzbar ist, und faellt sonst still
auf die CPU zurueck.

## Suche

Drei Modi in der Suchleiste:

- **Auto**: erst exakte Treffer aus Dateinamen, Tags und Metadaten, danach
  inhaltlich passende Clips
- **Text**: nur Volltext
- **Inhalt**: nur Bildinhalt, etwa "Sonnenuntergang am Wasser"

Die Filterleiste kombiniert Facetten: innerhalb einer Kategorie "oder",
zwischen Kategorien "und".

## Bildlook

Reihenfolge der Erkennung:

1. Ausdrueckliches Kameraprofil in den Metadaten (V-Log, C-Log3, S-Log3 ...)
2. Hinweis im Pfad, etwa ein Ordner `Export` oder `SLOG`
3. HDR-Transferfunktion PQ oder HLG laut Datei
4. Export-Signatur im Encoder-Feld (Final Cut, Resolve, Premiere)
5. 10 Bit ohne Export-Signatur gilt als LOG
6. 8 Bit Rec.709 gilt als nicht gegradet

In der Detailansicht steht bei jedem Clip, warum die Automatik so entschieden
hat. Per Klick ueberschreibbar, die Korrektur gewinnt danach immer. Die Regeln
stehen in `backend/app/metadata/rules.py`.

## Einsortieren

Unter "Werkzeuge", immer zweistufig: **Plan erstellen** zeigt jede geplante
Bewegung, **Verschieben** fuehrt sie aus, **Rueckgaengig** nimmt einen ganzen
Durchgang zurueck. Schema ueber `FDB_ORGANIZE_PATTERN`, verfuegbar sind
`{year}`, `{month}`, `{day}` und `{camera}`.

## Einstellungen

| Variable | Standard | Bedeutung |
|---|---|---|
| `FDB_PORT` | 8080 | Port der Weboberflaeche |
| `FDB_WORKER_COUNT` | 2 | parallele Hintergrundaufgaben |
| `FDB_PROXY_HEIGHT` | 720 | Hoehe der Browser-Previews |
| `FDB_PROXY_CRF` | 26 | Qualitaet der Previews, kleiner ist besser |
| `FDB_HWACCEL` | auto | `auto`, `vaapi` oder `off` |
| `FDB_SEMANTIC_ENABLED` | true | inhaltliche Suche |
| `FDB_RESCAN_INTERVAL_MINUTES` | 60 | automatischer Rescan, 0 schaltet ihn ab |
| `FDB_ORGANIZE_UPLOADS` | true | Uploads direkt einsortieren |
| `FDB_ORGANIZE_PATTERN` | `{year}/{year}-{month}/{camera}` | Ordnerschema |

Vollstaendige Liste in der `.env.example`. Bleibt `FDB_AUTH_PASSWORD` leer,
laeuft die Oberflaeche ohne Anmeldung. Das ist nur fuer ein abgeschottetes
Heimnetz gedacht.

## Entwicklung

```bash
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
FDB_MEDIA_ROOT=./testmedia FDB_DATA_DIR=./data \
  PYTHONPATH=backend .venv/bin/python -m uvicorn app.main:app --reload --port 8099

cd frontend && npm install && npm run dev   # Port 5173, leitet /api an 8099

cd backend && ../.venv/bin/python -m pytest
```

API-Dokumentation unter `/api/docs`.

## Aufbau

```
backend/app/
  main.py            FastAPI-App, Lifespan, Auslieferung der Oberflaeche
  scanner.py         Verzeichnisdurchlauf und Dateiueberwachung
  jobs.py            Warteschlange und Worker
  tasks.py           Kette probe, poster, proxy, sprite, embed
  organize.py        Einsortieren mit Plan, Ausfuehrung und Undo
  metadata/          ffprobe, exiftool, Sony-Sidecar, Erkennungsregeln
  media/             Poster, Sprite, Proxy, VAAPI-Erkennung
  search/            Volltext, Facetten, CLIP-Vektorsuche
  api/               HTTP-Endpunkte
frontend/src/        React-Oberflaeche
```
