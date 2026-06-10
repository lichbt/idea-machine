"""Cross-run pain memory.

Drops freshly-scraped signals whose pain is too close to one the machine has
ALREADY evaluated (every `ValidatedIdea.pain_point_title` ever scored). This stops
organic sources from re-surfacing the same pains run after run, so each run
explores new ground — and saves the validator/SWOT cost of re-scoring a known
pain. The "memory" is just the validated-idea history; no extra storage.

Degrades gracefully: if embeddings are unavailable, everything passes through.
"""
import logging

import config
from db.models import ValidatedIdea, get_session

log = logging.getLogger(__name__)


def _signal_pain(signal):
    """The crisp pain line to compare — the first line (the labeled pain
    statement, or the title) rather than the raw evidence beneath it."""
    return ((signal.get("content") or "").split("\n", 1)[0])[:200]


def filter_novel(signals, threshold=None):
    """Return (kept_signals, dropped_count). A signal is dropped if its pain is
    more similar than the threshold to any already-evaluated pain."""
    if not config.PAIN_MEMORY or not signals:
        return signals, 0

    session = get_session()
    try:
        memory = [t for (t,) in
                  session.query(ValidatedIdea.pain_point_title).all() if t]
    finally:
        session.close()
    if not memory:
        return signals, 0

    try:
        from sentence_transformers import util
        from utils.deduplicator import _get_model
        model = _get_model()
        mem_emb = model.encode(memory, convert_to_tensor=True)
        sig_emb = model.encode([_signal_pain(s) for s in signals],
                               convert_to_tensor=True)
        sim = util.cos_sim(sig_emb, mem_emb)  # [n_signals, n_memory]
    except Exception as e:  # noqa: BLE001 — never block discovery
        log.warning("Pain memory unavailable (%s); keeping all signals", e)
        return signals, 0

    thr = config.PAIN_MEMORY_THRESHOLD if threshold is None else threshold
    kept, dropped = [], 0
    for i, s in enumerate(signals):
        if float(sim[i].max()) > thr:
            dropped += 1
        else:
            kept.append(s)
    return kept, dropped
