# FootageDB

Selbstgehostete B-Roll-Bibliothek fuer das eigene NAS. Indexiert einen
Footage-Ordner, erzeugt Vorschaubilder und abspielbare Previews und macht den
ganzen Bestand ueber eine Weboberflaeche durchsuchbar.

- Vorschau beim Drueberfahren, ohne dass Video geladen wird
- Wiedergabe im Browser auch bei HEVC, 10 Bit, HDR oder 4K
- Metadaten aus ffprobe, exiftool und Sony-XML-Sidecars
- Erkennt automatisch LOG, graded, HDR oder Rec.709
- Suche nach Bildinhalt ueber ein lokales CLIP-Modell, ohne Cloud
- Erkennt 360-Material und rechnet dafuer brauchbare Vorschaubilder
- Upload grosser Dateien blockweise, mit Wiederaufnahme nach Abbruch, Tags
  direkt beim Hochladen
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
FDB_SECRET_KEY=<openssl rand -hex 32>
PUID=1000                            # id -u
PGID=1000                            # id -g
```

Oberflaeche: `http://<nas-ip>:8080`

## Installation auf Unraid

Es gibt ein fertiges Image unter `ghcr.io/kchromik/footage-db:latest` und eine
Vorlage in `unraid/footagedb.xml`.

**Vorbereitung.** Im Unraid-Terminal einen Schluessel erzeugen und notieren:

```bash
openssl rand -hex 32
```

**Weg 1: Vorlage laden.** Das Feld *Template* unter *Add Container* ist ein
Auswahlmenue, dort laesst sich keine URL eintragen. Die Vorlage kommt stattdessen
in den Vorlagenordner auf dem USB-Stick, danach steht sie im Menue:

```bash
mkdir -p /boot/config/plugins/dockerMan/templates-user
wget -O /boot/config/plugins/dockerMan/templates-user/my-FootageDB.xml \
  https://raw.githubusercontent.com/kchromik/Footage-DB/main/unraid/footagedb.xml
```

Docker-Seite neu laden, *Add Container*, unter *Template* den Eintrag
**FootageDB** waehlen. Danach nur noch anpassen: Footage-Ordner (Standard
`/mnt/user/Footage`) und `FDB_SECRET_KEY`. Der Rest passt fuer Unraid bereits.

**Weg 2: von Hand.** Docker-Reiter, *Add Container*, oben rechts auf *Advanced
View* schalten:

| Feld | Wert |
|---|---|
| Repository | `ghcr.io/kchromik/footage-db:latest` |
| Network Type | Bridge |
| WebUI | `http://[IP]:[PORT:8080]/` |

Der Rest ueber *Add another Path, Port, Variable, Label or Device*:

| Typ | Container-Pfad oder Key | Wert |
|---|---|---|
| Port | `8080` | `8080`, TCP |
| Path | `/media` | dein Footage-Share, Read/Write |
| Path | `/data` | `/mnt/user/appdata/footagedb`, Read/Write |
| Variable | `FDB_SECRET_KEY` | der erzeugte Schluessel |
| Variable | `PUID` | `99` |
| Variable | `PGID` | `100` |
| Variable | `TZ` | `Europe/Berlin` |

**Weg 3: Docker Compose.** Mit dem Plugin *Compose Manager* aus den Community
Applications: neuen Stack anlegen, die `docker-compose.yml` aus dem Repo
einfuegen und daneben eine `.env` nach dem Muster der `.env.example` pflegen.

### Worauf du auf Unraid achten solltest

- **PUID 99 und PGID 100.** Das ist `nobody:users`, dem auf Unraid die Shares
  gehoeren. Mit den sonst ueblichen 1000/1000 duerfte FootageDB nichts
  schreiben, Uploads und Einsortieren wuerden scheitern.
- **Das Datenverzeichnis waechst mit.** Dort liegen Previews und
  Vorschaubilder, grob 5 Prozent der Groesse deines Footage-Ordners, plus
  600 MB fuer das Suchmodell. Bei 2 TB Footage sind das rund 100 GB. Passt das
  nicht auf deinen Cache, leg `/data` auf ein Share mit Platz.
- **Datenbank auf SSD.** Wenn das Share auf dem Array liegt, wird die
  Oberflaeche zaeh. Cache-Prefer ist die richtige Einstellung.
- **Hardware-Encoding.** Hat deine CPU eine Intel-iGPU, unter *Extra
  Parameters* `--device=/dev/dri` eintragen. Die noetigen VAAPI-Treiber sind im
  Image enthalten. FootageDB prueft beim Start selbst, ob das nutzbar ist, und
  faellt sonst still auf die CPU zurueck. Ob es greift, steht unter "Bibliothek
  in Zahlen". Zum Nachsehen im Container: `vainfo`.
- **Image privat oder oeffentlich.** Nach dem ersten CI-Lauf liegt das Image in
  der GitHub Container Registry und ist zunaechst privat. Auf der Paketseite
  unter *Package settings* auf *Public* stellen, sonst muss sich Unraid vorher
  mit `docker login ghcr.io` anmelden.

## Installation auf einem UGREEN NAS

UGOS bringt im App Center eine Docker-App mit, die Compose versteht. Eine
fertige Datei liegt in `ugos/docker-compose.yml`.

1. **Ordner anlegen.** In der Dateiverwaltung einen Ordner fuer die Daten
   erstellen, zum Beispiel `docker/footagedb` auf `volume1`.
2. **Docker-App oeffnen**, links auf *Project*, dann *Create Project*.
3. Name `footagedb` vergeben, als Pfad den eben angelegten Ordner waehlen und
   den Inhalt von `ugos/docker-compose.yml` einfuegen.
4. Vor dem Start zwei Zeilen pruefen: den Pfad deines Footage-Ordners
   (`/volume1/Footage`) und den Port, falls 8080 schon belegt ist.
5. Starten, danach `http://<nas-ip>:8080` aufrufen. Der Einrichtungsassistent
   uebernimmt den Rest.

### Rechte

Das ist auf jedem NAS die haeufigste Huerde. Der Assistent zeigt unter
*Systempruefung* an, wem dein Footage-Ordner gehoert und als wem der Container
laeuft. Stimmen die Zahlen nicht ueberein und laesst sich nicht schreiben,
nennt er dir direkt die richtigen Werte. Die traegst du im Projekt bei `PUID`
und `PGID` ein und startest neu. Ohne SSH-Zugang ist das der einzige
verlaessliche Weg, an diese Zahlen zu kommen.

### Hardware-Encoding

Erst ohne starten. Laeuft alles, im Projekt die zwei auskommentierten Zeilen
fuer `/dev/dri` aktivieren und neu starten. Faehrt der Container danach nicht
hoch, gibt es das Geraet nicht, dann wieder auskommentieren. Ob es greift,
steht unter "Bibliothek in Zahlen".

## Einrichtungsassistent

Beim ersten Aufruf fuehrt ein Assistent durch die Einrichtung:

1. **Systempruefung**: ist der Medienordner da, les- und beschreibbar, wie viel
   Platz ist frei, sind ffmpeg und exiftool vorhanden, laesst sich die iGPU
   nutzen
2. **Zugang**: Benutzername und Passwort, gespeichert als scrypt-Hash in der
   Datenbank. Steht in der `.env` schon ein Passwort, entfaellt der Schritt
3. **Bibliothek**: zeigt, wie viele Dateien im Medienordner liegen und wie lange
   die erste Verarbeitung ungefaehr dauert
4. **Verarbeitung**: Qualitaet der Previews, gleichzeitige Aufgaben,
   Hardware-Encoding, Suche nach Bildinhalt. Die Vorschlaege richten sich nach
   der gefundenen Hardware
5. **Ablage**: wohin hochgeladene Dateien wandern
6. **Abschluss**: Zusammenfassung, danach startet der erste Scan

Alle Werte lassen sich spaeter unter "Werkzeuge" wieder aendern, ohne den
Container neu zu bauen.

Solange kein Passwort gesetzt ist, ist die Oberflaeche ohne Anmeldung
erreichbar. Ruf sie deshalb direkt nach dem Start auf und richte den Zugang
ein, oder trag vorher ein `FDB_AUTH_PASSWORD` in die `.env`.

Der erste Scan laeuft im Hintergrund: die Kacheln fuellen sich nach und nach,
suchen kannst du sofort. Fuer die inhaltliche Suche werden einmalig rund 600 MB
Modelldaten geladen.

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

Vollstaendige Liste in der `.env.example`. Was ueber den Assistenten oder unter
"Werkzeuge" geaendert wird, landet in der Datenbank und gewinnt danach gegen die
Umgebungsvariable.

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
