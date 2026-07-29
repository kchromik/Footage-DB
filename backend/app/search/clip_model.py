"""CLIP ViT-B/32 ueber ONNX Runtime, laeuft komplett lokal auf der CPU.

Die Modelldateien werden beim ersten Bedarf nach /data/models geladen.
Schlaegt das fehl, bleibt die App voll funktionsfaehig, nur die inhaltliche
Suche ist dann aus.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import settings

log = logging.getLogger(__name__)

REPO = "Xenova/clip-vit-base-patch32"
BASE_URL = f"https://huggingface.co/{REPO}/resolve/main"

IMAGE_SIZE = 224
CONTEXT_LENGTH = 77
EMBED_DIM = 512

# Normalisierung wie im Original-CLIP
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)


@dataclass
class ModelFile:
    name: str
    url: str
    min_size: int


def _files(quantized: bool) -> list[ModelFile]:
    suffix = "_quantized" if quantized else ""
    return [
        ModelFile(
            "vision_model.onnx",
            f"{BASE_URL}/onnx/vision_model{suffix}.onnx",
            50_000_000 if quantized else 300_000_000,
        ),
        ModelFile(
            "text_model.onnx",
            f"{BASE_URL}/onnx/text_model{suffix}.onnx",
            40_000_000 if quantized else 200_000_000,
        ),
        ModelFile("tokenizer.json", f"{BASE_URL}/tokenizer.json", 1_000_000),
    ]


class ModelUnavailable(RuntimeError):
    pass


class ClipModel:
    """Laedt die Modelle traege und teilt sie zwischen allen Workern."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._vision = None
        self._text = None
        self._tokenizer = None
        self._status = "nicht geladen"
        self._failed = False

    # --- Zustand ---------------------------------------------------

    @property
    def status(self) -> str:
        return self._status

    @property
    def ready(self) -> bool:
        return self._vision is not None and self._text is not None

    @property
    def failed(self) -> bool:
        return self._failed

    def model_dir(self) -> Path:
        return settings.models_dir / settings.semantic_model

    # --- Laden -----------------------------------------------------

    def ensure_loaded(self, download: bool = True) -> None:
        if self.ready:
            return
        with self._lock:
            if self.ready:
                return
            if self._failed and not download:
                raise ModelUnavailable(self._status)
            try:
                self._load(download=download)
                self._failed = False
            except Exception as exc:  # noqa: BLE001
                self._failed = True
                self._status = f"nicht verfuegbar: {exc}"
                log.warning("CLIP-Modell konnte nicht geladen werden: %s", exc)
                raise ModelUnavailable(str(exc)) from exc

    def _load(self, download: bool) -> None:
        import onnxruntime as ort

        directory = self.model_dir()
        directory.mkdir(parents=True, exist_ok=True)
        quantized = _quantized_wanted()

        for spec in _files(quantized):
            target = directory / spec.name
            if target.exists() and target.stat().st_size >= spec.min_size * 0.9:
                continue
            if not download:
                raise ModelUnavailable(f"{spec.name} fehlt")
            self._status = f"laedt {spec.name}"
            _download(spec, target)

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.intra_op_num_threads = max(1, min(4, (settings.worker_count or 1) * 2))
        options.log_severity_level = 3

        self._vision = ort.InferenceSession(
            str(directory / "vision_model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self._text = ort.InferenceSession(
            str(directory / "text_model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )

        from tokenizers import Tokenizer

        tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        tokenizer.enable_truncation(max_length=CONTEXT_LENGTH)
        pad_id = tokenizer.token_to_id("<|endoftext|>") or 0
        tokenizer.enable_padding(
            length=CONTEXT_LENGTH, pad_id=pad_id, pad_token="<|endoftext|>"
        )
        self._tokenizer = tokenizer
        self._status = "bereit" + (" (quantisiert)" if quantized else "")
        log.info("CLIP-Modell geladen (%s)", self._status)

    # --- Inferenz --------------------------------------------------

    def encode_images(self, images) -> np.ndarray:
        """images: Liste von PIL-Bildern. Liefert normalisierte Vektoren."""
        self.ensure_loaded()
        batch = np.stack([_preprocess(image) for image in images]).astype(np.float32)
        feed = {self._vision.get_inputs()[0].name: batch}
        outputs = self._vision.run(None, feed)
        vectors = _pick_embedding(self._vision, outputs)
        return _normalize(vectors)

    def encode_text(self, texts: list[str]) -> np.ndarray:
        self.ensure_loaded()
        encoded = self._tokenizer.encode_batch(texts)
        input_ids = np.array([e.ids for e in encoded], dtype=np.int64)
        attention = np.array([e.attention_mask for e in encoded], dtype=np.int64)
        feed = {}
        for spec in self._text.get_inputs():
            if "attention" in spec.name:
                feed[spec.name] = attention
            else:
                feed[spec.name] = input_ids
        outputs = self._text.run(None, feed)
        vectors = _pick_embedding(self._text, outputs)
        return _normalize(vectors)


def _quantized_wanted() -> bool:
    return bool(settings.semantic_quantized)


def _pick_embedding(session, outputs) -> np.ndarray:
    names = [spec.name for spec in session.get_outputs()]
    for index, name in enumerate(names):
        if "embed" in name.lower():
            return np.asarray(outputs[index], dtype=np.float32)
    # Fallback: die erste zweidimensionale Ausgabe passender Breite
    for array in outputs:
        array = np.asarray(array)
        if array.ndim == 2:
            return array.astype(np.float32)
    raise ModelUnavailable(f"Unerwartete Modellausgabe: {names}")


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vectors / norms).astype(np.float32)


def _preprocess(image) -> np.ndarray:
    """Kurze Kante auf 224 skalieren, mittig beschneiden, normalisieren."""
    from PIL import Image

    image = image.convert("RGB")
    width, height = image.size
    scale = IMAGE_SIZE / min(width, height)
    new_size = (max(IMAGE_SIZE, round(width * scale)), max(IMAGE_SIZE, round(height * scale)))
    image = image.resize(new_size, Image.BICUBIC)

    left = (image.width - IMAGE_SIZE) // 2
    top = (image.height - IMAGE_SIZE) // 2
    image = image.crop((left, top, left + IMAGE_SIZE, top + IMAGE_SIZE))

    array = np.asarray(image, dtype=np.float32) / 255.0
    array = (array - MEAN) / STD
    return np.transpose(array, (2, 0, 1))


def _download(spec: ModelFile, target: Path) -> None:
    import httpx

    log.info("Lade Modelldatei %s", spec.name)
    tmp = target.with_suffix(target.suffix + ".part")
    with httpx.stream(
        "GET", spec.url, follow_redirects=True, timeout=httpx.Timeout(60.0, read=300.0)
    ) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_bytes(1024 * 256):
                handle.write(chunk)
    if tmp.stat().st_size < spec.min_size * 0.9:
        tmp.unlink(missing_ok=True)
        raise ModelUnavailable(f"{spec.name} unvollstaendig geladen")
    tmp.replace(target)
    log.info("Modelldatei %s bereit (%.0f MB)", spec.name, target.stat().st_size / 1e6)


model = ClipModel()
