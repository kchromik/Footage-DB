-- FootageDB Schema
-- Wird bei jedem Start idempotent angewendet.

CREATE TABLE IF NOT EXISTS clips (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    path              TEXT    NOT NULL UNIQUE,   -- relativ zu MEDIA_ROOT, posix
    filename          TEXT    NOT NULL,
    original_filename TEXT,
    folder            TEXT    NOT NULL DEFAULT '',
    ext               TEXT    NOT NULL DEFAULT '',
    size_bytes        INTEGER NOT NULL DEFAULT 0,
    mtime             REAL    NOT NULL DEFAULT 0,
    content_hash      TEXT,

    status            TEXT    NOT NULL DEFAULT 'new',   -- new|indexed|error|missing
    error             TEXT,

    -- technische Daten aus ffprobe
    duration          REAL,
    width             INTEGER,
    height            INTEGER,
    fps               REAL,
    video_codec       TEXT,
    audio_codec       TEXT,
    audio_channels    INTEGER,
    pix_fmt           TEXT,
    bit_depth         INTEGER,
    color_transfer    TEXT,
    color_primaries   TEXT,
    color_space       TEXT,
    bitrate           INTEGER,
    rotation          INTEGER NOT NULL DEFAULT 0,
    container         TEXT,
    encoder           TEXT,
    projection        TEXT,       -- equirectangular|half equirectangular|cubemap|eac
    stereo_mode       TEXT,       -- mono|top-bottom|left-right

    -- inhaltliche Daten aus ffprobe/exiftool
    camera_make       TEXT,
    camera_model      TEXT,
    camera_label      TEXT,
    lens              TEXT,
    recorded_at       TEXT,       -- ISO 8601, lokale Zeit der Kamera
    recorded_source   TEXT,       -- metadata|filename|mtime
    gps_lat           REAL,
    gps_lon           REAL,
    look              TEXT,       -- log|rec709|hdr|graded|unknown
    look_manual       TEXT,       -- vom Benutzer gesetzt, gewinnt immer
    look_reason       TEXT,       -- warum die Automatik so entschieden hat

    -- Benutzerdaten
    title             TEXT,
    notes             TEXT,
    favorite          INTEGER NOT NULL DEFAULT 0,
    rating            INTEGER NOT NULL DEFAULT 0,

    -- Ableitungen
    poster_status     TEXT    NOT NULL DEFAULT 'pending',  -- pending|ready|failed
    sprite_status     TEXT    NOT NULL DEFAULT 'pending',
    sprite_cols       INTEGER,
    sprite_rows       INTEGER,
    sprite_count      INTEGER,
    sprite_tile_w     INTEGER,
    sprite_tile_h     INTEGER,
    proxy_status      TEXT    NOT NULL DEFAULT 'pending',  -- pending|ready|failed|skipped
    proxy_size        INTEGER,
    embed_status      TEXT    NOT NULL DEFAULT 'pending',

    created_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at        TEXT    NOT NULL DEFAULT (datetime('now')),
    indexed_at        TEXT,
    seen_at           TEXT
);

CREATE INDEX IF NOT EXISTS idx_clips_hash        ON clips(content_hash);
CREATE INDEX IF NOT EXISTS idx_clips_recorded    ON clips(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_clips_camera      ON clips(camera_label);
CREATE INDEX IF NOT EXISTS idx_clips_look        ON clips(look);
CREATE INDEX IF NOT EXISTS idx_clips_status      ON clips(status);
CREATE INDEX IF NOT EXISTS idx_clips_height      ON clips(height);
CREATE INDEX IF NOT EXISTS idx_clips_duration    ON clips(duration);
CREATE INDEX IF NOT EXISTS idx_clips_favorite    ON clips(favorite);
CREATE INDEX IF NOT EXISTS idx_clips_folder      ON clips(folder);

CREATE TABLE IF NOT EXISTS tags (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    category    TEXT NOT NULL DEFAULT 'custom',  -- camera|lens|look|tech|source|custom
    color       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS clip_tags (
    clip_id  INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags(id)  ON DELETE CASCADE,
    source   TEXT NOT NULL DEFAULT 'manual',      -- manual|auto
    PRIMARY KEY (clip_id, tag_id)
);
CREATE INDEX IF NOT EXISTS idx_clip_tags_tag ON clip_tags(tag_id);

-- Volltextsuche über Dateiname, Ordner, Kamera, Tags und Notizen
CREATE VIRTUAL TABLE IF NOT EXISTS clips_fts USING fts5(
    body,
    clip_id UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS embeddings (
    clip_id     INTEGER PRIMARY KEY REFERENCES clips(id) ON DELETE CASCADE,
    model       TEXT    NOT NULL,
    dim         INTEGER NOT NULL,
    vector      BLOB    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    type         TEXT    NOT NULL,      -- probe|preview|proxy|embed
    clip_id      INTEGER,
    payload      TEXT,
    state        TEXT    NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
    priority     INTEGER NOT NULL DEFAULT 100,
    attempts     INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now')),
    started_at   TEXT,
    finished_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, priority, id);
-- verhindert doppelte offene Jobs für denselben Clip
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_open_unique
    ON jobs(type, clip_id) WHERE state IN ('queued', 'running');

CREATE TABLE IF NOT EXISTS moves (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    batch       TEXT    NOT NULL,
    clip_id     INTEGER,
    from_path   TEXT    NOT NULL,
    to_path     TEXT    NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'done',   -- done|reverted|failed
    error       TEXT,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_moves_batch ON moves(batch);

CREATE TABLE IF NOT EXISTS collections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE COLLATE NOCASE,
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS collection_clips (
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    clip_id       INTEGER NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    position      INTEGER NOT NULL DEFAULT 0,
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (collection_id, clip_id)
);

CREATE TABLE IF NOT EXISTS uploads (
    id            TEXT PRIMARY KEY,
    filename      TEXT    NOT NULL,
    size_bytes    INTEGER NOT NULL,
    chunk_size    INTEGER NOT NULL,
    chunk_count   INTEGER NOT NULL,
    state         TEXT    NOT NULL DEFAULT 'open',  -- open|complete|aborted
    target_path   TEXT,
    subdir        TEXT,
    tags          TEXT,          -- JSON-Liste, beim Upload vergebene Tags
    clip_id       INTEGER,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS upload_chunks (
    upload_id  TEXT    NOT NULL REFERENCES uploads(id) ON DELETE CASCADE,
    idx        INTEGER NOT NULL,
    size       INTEGER NOT NULL,
    PRIMARY KEY (upload_id, idx)
);

CREATE TABLE IF NOT EXISTS settings (
    key         TEXT PRIMARY KEY,
    value       TEXT,
    updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
