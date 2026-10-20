"""Sentence embeddings, computed locally (no API, no cost)."""

import math
import threading
from collections.abc import Sequence
from typing import Protocol

from osint.models import EMBEDDING_DIM

# Multilingual (50+ languages, aligned across them), small and fast on CPU. On our labelled
# sample it separated same-event pairs from same-topic pairs better than bge-small and
# multilingual-e5-large. It reads about the first 128 tokens, which is the lede.
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
LEDE_CHARS = 600


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


def embedding_text(title: str | None, content: str | None) -> str:
    return f"{title or ''}. {(content or '')[:LEDE_CHARS]}".strip()


def normalise(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector)) or 1.0
    return [float(x) / norm for x in vector]


class FastEmbedder:
    """ONNX runtime embedder (fastembed). The model is downloaded on first use."""

    model_name = MODEL_NAME

    def __init__(self, threads: int | None = None) -> None:
        self._threads = threads
        self._model = None
        self._lock = threading.Lock()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                self._model = TextEmbedding(self.model_name, threads=self._threads)
            vectors = [normalise(v) for v in self._model.embed(list(texts), batch_size=16)]
        if vectors and len(vectors[0]) != EMBEDDING_DIM:
            raise RuntimeError(
                f"{self.model_name} gives {len(vectors[0])} dimensions; "
                f"the schema expects {EMBEDDING_DIM}"
            )
        return vectors
