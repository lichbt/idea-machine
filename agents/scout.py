"""Agent 1 — Scout.

Scrapes pain points from all sources, deduplicates (exact hash + semantic
clustering), enforces the minimum-signal cluster threshold, caps output, and
writes pending rows to raw_signals.

Resilience: a failure in any single scraper is logged and skipped — the
pipeline never halts on one bad source.
"""
import logging
from datetime import datetime

import config
from db.models import RawSignal, get_session
from scrapers import appstore, appsumo, hackernews, playstore, producthunt, reddit
from utils.deduplicator import content_hash, most_similar

log = logging.getLogger(__name__)

_SCRAPERS = {
    "reddit": reddit.scrape,
    "hackernews": hackernews.scrape,
    "producthunt": producthunt.scrape,
    "appstore": appstore.scrape,
    "playstore": playstore.scrape,
    "appsumo": appsumo.scrape,
}


def _gather(sources):
    signals = []
    for name in sources:
        fn = _SCRAPERS.get(name)
        if not fn:
            continue
        try:
            signals.extend(fn())
        except Exception as e:  # belt-and-suspenders; scrapers already guard
            log.error("Scraper '%s' raised, skipping: %s", name, e)
    return signals


def _dedup_exact(signals):
    """Attach content_hash and drop in-batch exact duplicates."""
    seen = set()
    out = []
    for s in signals:
        h = content_hash(s.get("url"), s.get("content"))
        if h in seen:
            continue
        seen.add(h)
        s["content_hash"] = h
        out.append(s)
    return out


def _cluster(signals, min_size):
    """Greedy semantic clustering. Returns the representative signal of each
    cluster whose size >= min_size (representative = longest content).

    Degrades gracefully: if embeddings are unavailable, returns all signals
    unchanged (clustering simply skipped, logged).
    """
    if not signals:
        return []
    texts = [s["content"] for s in signals]
    # Probe the model once; most_similar returns (None, 0.0) if it can't run.
    probe_idx, _ = most_similar(texts[0], texts[1:2] if len(texts) > 1 else [texts[0]])
    if probe_idx is None and len(texts) > 1:
        log.warning("Clustering unavailable; passing all signals through")
        return signals

    try:
        from sentence_transformers import util
        from utils.deduplicator import _get_model
        model = _get_model()
        embeddings = model.encode(texts, convert_to_tensor=True)
        sim = util.cos_sim(embeddings, embeddings)
    except Exception as e:
        log.warning("Clustering failed (%s); passing all signals through", e)
        return signals

    assigned = [False] * len(signals)
    representatives = []
    for i in range(len(signals)):
        if assigned[i]:
            continue
        members = [i]
        assigned[i] = True
        for j in range(i + 1, len(signals)):
            if assigned[j]:
                continue
            if float(sim[i][j]) > config.SIMILARITY_THRESHOLD:
                members.append(j)
                assigned[j] = True
        if len(members) >= min_size:
            rep = max(members, key=lambda k: len(signals[k]["content"]))
            representatives.append(signals[rep])
        else:
            log.info("insufficient_signal: cluster of %d (<%d) dropped",
                     len(members), min_size)
    return representatives


def _interleave_by_source(signals, cap):
    """Round-robin across sources so the cap doesn't starve later sources.
    Preserves per-source order; takes one from each source in turn until cap."""
    buckets = {}
    for s in signals:
        buckets.setdefault(s.get("source"), []).append(s)
    out = []
    while len(out) < cap and any(buckets.values()):
        for src in list(buckets.keys()):
            if buckets[src]:
                out.append(buckets[src].pop(0))
                if len(out) >= cap:
                    break
    return out


def run(sources=None, min_cluster=None, cap=None):
    """Run the Scout. Returns the number of new pending signals written."""
    sources = sources or list(_SCRAPERS.keys())
    min_cluster = config.MIN_SIGNAL_CLUSTER if min_cluster is None else min_cluster
    cap = config.MAX_IDEAS_PER_RUN if cap is None else cap

    raw = _gather(sources)
    log.info("Scout gathered %d raw signals from %s", len(raw), sources)

    deduped = _dedup_exact(raw)
    clustered = _cluster(deduped, min_cluster)
    selected = _interleave_by_source(clustered, cap)

    session = get_session()
    written = 0
    try:
        for s in selected:
            exists = session.query(RawSignal).filter_by(
                content_hash=s["content_hash"]
            ).first()
            if exists:
                continue
            session.add(RawSignal(
                source=s["source"],
                url=s.get("url"),
                content=s.get("content"),
                content_hash=s["content_hash"],
                scraped_at=datetime.utcnow(),
                status="pending",
            ))
            written += 1
        session.commit()
    finally:
        session.close()

    log.info("Scout wrote %d new pending signals", written)
    return written
