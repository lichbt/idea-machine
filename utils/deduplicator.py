"""Deduplication helpers.

Two layers:
  1. content_hash  — exact-ish fingerprint (url + content[:200]) for raw signals.
  2. semantic      — sentence-transformers cosine similarity for finished ideas.

The sentence-transformers model is heavy and imported lazily so that scraping
and validation do not pay its load cost.
"""
import hashlib
import logging

import config

log = logging.getLogger(__name__)

_model = None


def content_hash(url, content):
    """Stable fingerprint for dedup: url + first 200 chars of content."""
    basis = f"{url or ''}{(content or '')[:200]}"
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("all-MiniLM-L6-v2")
    return _model


def most_similar(text, candidates):
    """Return (best_index, score) of the most similar candidate, or (None, 0.0).

    `candidates` is a list of strings. Returns cosine similarity in [0, 1].
    """
    if not candidates:
        return None, 0.0
    try:
        from sentence_transformers import util
        model = _get_model()
        query_emb = model.encode(text, convert_to_tensor=True)
        cand_emb = model.encode(candidates, convert_to_tensor=True)
        scores = util.cos_sim(query_emb, cand_emb)[0]
        best_idx = int(scores.argmax())
        return best_idx, float(scores[best_idx])
    except Exception as e:
        log.warning("Semantic similarity check failed, skipping: %s", e)
        return None, 0.0


def is_duplicate(text, candidates, threshold=None):
    """Return (flag, best_index, score) where flag = score > threshold."""
    threshold = config.SIMILARITY_THRESHOLD if threshold is None else threshold
    idx, score = most_similar(text, candidates)
    return (idx is not None and score > threshold), idx, score
