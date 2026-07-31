"""Inhaltliche Suche: Bildvektoren pro Clip, Textvektor pro Suchanfrage.

Der Vektorindex liegt als numpy-Matrix im Arbeitsspeicher. Bei 50.000 Clips
sind das rund 50 MB und eine Suche dauert wenige Millisekunden, deshalb
braucht es keine zusätzliche Vektordatenbank.
"""

from __future__ import annotations

import logging
import tempfile
import threading
from pathlib import Path

import numpy as np

from ..config import settings
from ..db import get_conn
from ..events import bus
from ..media import preview
from ..settings_store import runtime
from .clip_model import EMBED_DIM, ModelUnavailable, model

log = logging.getLogger(__name__)


class VectorIndex:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: np.ndarray = np.zeros(0, dtype=np.int64)
        self._matrix: np.ndarray = np.zeros((0, EMBED_DIM), dtype=np.float32)
        self._loaded = False

    def load(self, force: bool = False) -> None:
        with self._lock:
            if self._loaded and not force:
                return
            rows = get_conn().execute(
                "SELECT clip_id, vector FROM embeddings ORDER BY clip_id"
            ).fetchall()
            if rows:
                self._ids = np.array([row["clip_id"] for row in rows], dtype=np.int64)
                self._matrix = np.stack(
                    [np.frombuffer(row["vector"], dtype=np.float16) for row in rows]
                ).astype(np.float32)
            else:
                self._ids = np.zeros(0, dtype=np.int64)
                self._matrix = np.zeros((0, EMBED_DIM), dtype=np.float32)
            self._loaded = True
            log.info("Vektorindex geladen: %d Clips", len(self._ids))

    def upsert(self, clip_id: int, vector: np.ndarray) -> None:
        with self._lock:
            if not self._loaded:
                return  # wird beim nächsten Laden ohnehin mitgenommen
            position = np.searchsorted(self._ids, clip_id)
            if position < len(self._ids) and self._ids[position] == clip_id:
                self._matrix[position] = vector
                return
            self._ids = np.insert(self._ids, position, clip_id)
            self._matrix = np.insert(self._matrix, position, vector, axis=0)

    def remove(self, clip_id: int) -> None:
        with self._lock:
            if not self._loaded:
                return
            position = np.searchsorted(self._ids, clip_id)
            if position < len(self._ids) and self._ids[position] == clip_id:
                self._ids = np.delete(self._ids, position)
                self._matrix = np.delete(self._matrix, position, axis=0)

    def search(
        self, query: np.ndarray, limit: int = 200, allowed: set[int] | None = None
    ) -> list[tuple[int, float]]:
        self.load()
        with self._lock:
            if len(self._ids) == 0:
                return []
            ids = self._ids
            matrix = self._matrix
            if allowed is not None:
                mask = np.isin(ids, np.fromiter(allowed, dtype=np.int64, count=len(allowed)))
                ids = ids[mask]
                matrix = matrix[mask]
                if len(ids) == 0:
                    return []
            scores = matrix @ query.astype(np.float32)
            count = min(limit, len(scores))
            top = np.argpartition(-scores, count - 1)[:count]
            top = top[np.argsort(-scores[top])]
            return [(int(ids[i]), float(scores[i])) for i in top]

    @property
    def size(self) -> int:
        return len(self._ids)


index = VectorIndex()


def embed_clip(
    clip_id: int,
    source: Path,
    duration: float | None,
    color_transfer: str | None = None,
    projection: str | None = None,
    stereo_mode: str | None = None,
) -> None:
    """Berechnet den Bildvektor eines Clips aus mehreren Einzelbildern."""
    from PIL import Image

    conn = get_conn()
    try:
        model.ensure_loaded()
    except ModelUnavailable as exc:
        conn.execute(
            "UPDATE clips SET embed_status='skipped' WHERE id=?", (clip_id,)
        )
        log.debug("Embedding übersprungen (%s)", exc)
        return

    settings.tmp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=settings.tmp_dir) as tmp:
        frames = preview.extract_frames(
            source,
            max(1, settings.semantic_frames),
            336,
            duration,
            Path(tmp),
            color_transfer,
            projection,
            stereo_mode,
        )
        if not frames:
            conn.execute("UPDATE clips SET embed_status='failed' WHERE id=?", (clip_id,))
            return

        images = []
        for frame in frames:
            with Image.open(frame) as image:
                images.append(image.convert("RGB").copy())

        vectors = model.encode_images(images)

    mean = vectors.mean(axis=0)
    norm = float(np.linalg.norm(mean))
    if norm == 0:
        conn.execute("UPDATE clips SET embed_status='failed' WHERE id=?", (clip_id,))
        return
    mean = (mean / norm).astype(np.float32)

    conn.execute(
        "INSERT INTO embeddings(clip_id, model, dim, vector) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(clip_id) DO UPDATE SET model=excluded.model, dim=excluded.dim, "
        "vector=excluded.vector, created_at=datetime('now')",
        (clip_id, settings.semantic_model, len(mean), mean.astype(np.float16).tobytes()),
    )
    conn.execute("UPDATE clips SET embed_status='ready' WHERE id=?", (clip_id,))
    index.upsert(clip_id, mean)
    bus.publish("clip", id=clip_id, action="embed")


_QUERY_TEMPLATES = (
    "{}",
    "ein Foto von {}",
    "a photo of {}",
)


def encode_query(text: str) -> np.ndarray | None:
    """Mehrere Formulierungen mitteln, das stabilisiert kurze Suchbegriffe."""
    text = text.strip()
    if not text:
        return None
    try:
        model.ensure_loaded()
    except ModelUnavailable:
        return None
    prompts = [template.format(text) for template in _QUERY_TEMPLATES]
    vectors = model.encode_text(prompts)
    mean = vectors.mean(axis=0)
    norm = float(np.linalg.norm(mean))
    if norm == 0:
        return None
    return (mean / norm).astype(np.float32)


def search(text: str, limit: int = 300, allowed: set[int] | None = None):
    vector = encode_query(text)
    if vector is None:
        return []
    return index.search(vector, limit=limit, allowed=allowed)


def status() -> dict:
    return {
        "enabled": runtime.semantic_enabled,
        "model_status": model.status,
        "ready": model.ready,
        "indexed": index.size if index._loaded else _count_embeddings(),
        "pending": _count_pending(),
    }


def _count_embeddings() -> int:
    row = get_conn().execute("SELECT COUNT(*) AS n FROM embeddings").fetchone()
    return row["n"] if row else 0


def _count_pending() -> int:
    row = get_conn().execute(
        "SELECT COUNT(*) AS n FROM clips WHERE status='indexed' AND embed_status='pending'"
    ).fetchone()
    return row["n"] if row else 0
