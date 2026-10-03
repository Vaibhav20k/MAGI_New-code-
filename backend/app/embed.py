"""Local embeddings (agent 04's "meaning fingerprint"). Free, unlimited, runs on CPU."""

import asyncio
from functools import lru_cache

import numpy as np
from fastembed import TextEmbedding

from .config import get_settings

DIMS = 384


@lru_cache
def _model() -> TextEmbedding:
    s = get_settings()
    return TextEmbedding(s.embed_model, cache_dir=str(s.data_dir / "models"))


def embed_sync(texts: list[str]) -> list[np.ndarray]:
    if not texts:
        return []
    return [np.asarray(v, dtype=np.float32) for v in _model().embed(texts, batch_size=32)]


async def embed(texts: list[str]) -> list[np.ndarray]:
    return await asyncio.to_thread(embed_sync, texts)


async def embed_one(text: str) -> np.ndarray:
    return (await embed([text]))[0]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))
