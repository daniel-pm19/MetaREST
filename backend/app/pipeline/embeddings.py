"""Local text embeddings for the diversity filter (no data leaves the server).

``FastEmbedEmbedder`` runs an ONNX model with fastembed (light enough for a t3.medium);
the model is downloaded on first use into ``cache_dir`` (mount it as a volume in Docker
so it is not downloaded on every deploy). ``HashingEmbedder`` is a dependency-free
bag-of-tokens embedder for tests; do not use it for the experiments.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

Vector = list[float]


@runtime_checkable
class Embedder(Protocol):
    name: str

    async def embed(self, texts: Sequence[str]) -> list[Vector]: ...


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


class FastEmbedEmbedder:
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", *, cache_dir: str | None = None):
        self.name = f"fastembed:{model_name}"
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._model: Any | None = None
        self._lock = asyncio.Lock()

    def _load(self) -> Any:
        from fastembed import TextEmbedding  # lazy: heavy import, only when the filter runs

        return TextEmbedding(model_name=self.model_name, cache_dir=self.cache_dir)

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        if not texts:
            return []
        async with self._lock:
            if self._model is None:
                self._model = await asyncio.to_thread(self._load)
        model = self._model
        return await asyncio.to_thread(lambda: [[float(x) for x in v] for v in model.embed(list(texts))])


class HashingEmbedder:
    """Deterministic bag-of-tokens vectors (tests / offline only)."""

    def __init__(self, dims: int = 256):
        self.name = f"hashing:{dims}"
        self.dims = dims

    async def embed(self, texts: Sequence[str]) -> list[Vector]:
        vectors = []
        for text in texts:
            v = [0.0] * self.dims
            for token in re.findall(r"[\w$.\[\]*]+", text.lower()):
                v[int(hashlib.md5(token.encode()).hexdigest(), 16) % self.dims] += 1.0
            vectors.append(v)
        return vectors
