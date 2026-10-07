"""Embedding and re-ranking models, loaded once per process on first use.

EMBEDDING_MODEL is a sentence-transformers id or a local path (e.g. a fine-tuned e5).
EMBEDDING_MODEL="fake" is a deterministic hashing embedder for tests: no download, no torch,
and texts that share words still land close together, so retrieval tests stay meaningful.
"""

import hashlib
import re
import threading
from functools import lru_cache

import numpy as np
from django.conf import settings

from copilot.models import EMBEDDING_DIM

FAKE = "fake"
_lock = threading.Lock()


@lru_cache(maxsize=4)
def _model(name: str):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(name, device="cpu")


def embedder(name: str):
    # One load per process even when two requests arrive together (the load takes seconds).
    with _lock:
        return _model(name)


@lru_cache(maxsize=2)
def _cross_encoder(name: str):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(name, device="cpu")


def model_name() -> str:
    return settings.EMBEDDING_MODEL


# e5 models are trained with these prefixes; leaving them out costs several points of recall.
def _prefix(name: str, kind: str) -> str:
    return f"{kind}: " if "e5" in name.lower() else ""


_WORD = re.compile(r"\w+", re.U)


def _fake(texts: list[str]) -> np.ndarray:
    out = np.zeros((len(texts), EMBEDDING_DIM), dtype=np.float32)
    for row, text in enumerate(texts):
        for word in _WORD.findall(text.lower()):
            h = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=8).digest(), "big")
            out[row, h % EMBEDDING_DIM] += 1.0 if (h >> 32) & 1 else -1.0
        norm = np.linalg.norm(out[row])
        out[row] = out[row] / norm if norm else out[row]
        if not norm:
            out[row, 0] = 1.0  # pgvector cannot take a zero vector for cosine distance
    return out


def embed_passages(texts: list[str], name: str | None = None) -> np.ndarray:
    name = name or model_name()
    if not texts:
        return np.zeros((0, EMBEDDING_DIM), dtype=np.float32)
    if name == FAKE:
        return _fake(texts)
    p = _prefix(name, "passage")
    return embedder(name).encode(
        [p + t for t in texts], batch_size=32, normalize_embeddings=True, show_progress_bar=False
    )


def embed_query(text: str, name: str | None = None) -> np.ndarray:
    name = name or model_name()
    if name == FAKE:
        return _fake([text])[0]
    return embedder(name).encode(
        [_prefix(name, "query") + text], normalize_embeddings=True, show_progress_bar=False
    )[0]


def rerank_scores(query: str, passages: list[str], name: str | None = None) -> list[float]:
    name = name or settings.RERANKER_MODEL
    if not passages or not name:
        return []
    scores = _cross_encoder(name).predict([(query, p) for p in passages], show_progress_bar=False)
    return [float(s) for s in scores]
