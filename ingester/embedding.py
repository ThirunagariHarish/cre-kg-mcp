"""
Shared embedding helpers — imported by both ingester.streaming and
mcp_server.tools.semantic_search so the 80 MB sentence-transformers model is
loaded at most once per process.

N-P2-1: Extracted from duplicate _get_model() implementations.
"""

from __future__ import annotations

import structlog

log = structlog.get_logger()

_model = None
_TRANSFORMERS_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer  # type: ignore
    _TRANSFORMERS_AVAILABLE = True
except ImportError:
    pass


def get_model():
    """Return the singleton SentenceTransformer model (lazy-loaded)."""
    global _model
    if _model is None:
        if not _TRANSFORMERS_AVAILABLE:
            raise RuntimeError("sentence-transformers not installed")
        log.info("embedding_model_loading", model="all-MiniLM-L6-v2")
        _model = SentenceTransformer("all-MiniLM-L6-v2")
        log.info("embedding_model_loaded")
    return _model


def encode(text: str) -> list[float]:
    """Return a 384-dim normalised embedding for *text*."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.tolist()
