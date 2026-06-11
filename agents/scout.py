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
from scrapers import (
    appstore,
    appsumo,
    ecosystem,
    github,
    hackernews,
    playstore,
    producthunt,
    reddit,
    trustpilot,
)
from utils.deduplicator import content_hash, most_similar
from utils.pain import pain_score
from utils.ranking import discovery_score

log = logging.getLogger(__name__)

_SCRAPERS = {
    "reddit": reddit.scrape,
    "hackernews": hackernews.scrape,
    "producthunt": producthunt.scrape,
    "appstore": appstore.scrape,
    "playstore": playstore.scrape,
    "appsumo": appsumo.scrape,
    "github": github.scrape,
    "trustpilot": trustpilot.scrape,
    "ecosystem": ecosystem.scrape,
}


# Scrapers whose search terms the feedback seed planner can override.
_SEEDED_SCRAPERS = ("appstore", "playstore")


def _gather(sources, seed_terms=None):
    signals = []
    for name in sources:
        fn = _SCRAPERS.get(name)
        if not fn:
            continue
        try:
            if seed_terms and name in _SEEDED_SCRAPERS:
                signals.extend(fn(search_terms=seed_terms))
            else:
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
        rep = max(members, key=lambda k: len(signals[k]["content"]))
        if len(members) >= min_size:
            representatives.append(signals[rep])
        elif signals[rep].get("synthesized"):
            # Deliberately synthesized signals (ecosystem gaps) are single by
            # construction — the cross-mention evidence lives upstream, not in
            # this batch — so the cluster-size gate doesn't apply to them.
            representatives.append(signals[rep])
        else:
            # Novelty rescue: a rare but high-pain signal is exactly the kind of
            # underserved opportunity the popularity filter would otherwise drop.
            ps = pain_score(signals[rep]["content"])
            if ps >= config.PAIN_KEEP_THRESHOLD:
                signals[rep]["pain_score"] = ps
                representatives.append(signals[rep])
                log.info("novelty_rescue: cluster of %d kept (pain=%d)",
                         len(members), ps)
            else:
                log.info("insufficient_signal: cluster of %d (<%d) dropped (pain=%d)",
                         len(members), min_size, ps)
    return representatives


def _interleave_by_source(signals, cap):
    """Round-robin across sources so the cap doesn't starve later sources.
    Within each source the strongest signals (pain + willingness-to-pay +
    recency) go first, so when the cap bites it keeps the best, not an arbitrary
    slice."""
    buckets = {}
    for s in signals:
        buckets.setdefault(s.get("source"), []).append(s)
    for src in buckets:
        buckets[src].sort(key=discovery_score, reverse=True)
    out = []
    while len(out) < cap and any(buckets.values()):
        for src in list(buckets.keys()):
            if buckets[src]:
                out.append(buckets[src].pop(0))
                if len(out) >= cap:
                    break
    return out


def run(sources=None, min_cluster=None, cap=None, seed_terms=None):
    """Run the Scout. Returns the number of new pending signals written.

    seed_terms overrides the app-store search categories. When None and
    config.FEEDBACK_SEEDS is on, the seed planner generates fresh categories
    from verdict history (adaptive discovery); otherwise the scrapers use their
    static config lists.
    """
    sources = sources or list(_SCRAPERS.keys())
    min_cluster = config.MIN_SIGNAL_CLUSTER if min_cluster is None else min_cluster
    cap = config.MAX_IDEAS_PER_RUN if cap is None else cap

    if seed_terms is None and config.FEEDBACK_SEEDS:
        try:
            from agents.seed_planner import plan_seeds
            seed_terms = plan_seeds(config.FEEDBACK_SEED_COUNT,
                                    config.APPSTORE_SEARCH_TERMS)
            log.info("Feedback seeds (%d): %s", len(seed_terms), seed_terms)
        except Exception as e:  # noqa: BLE001 — never block discovery
            log.warning("Seed planning failed (%s); using static terms", e)
            seed_terms = None

    raw = _gather(sources, seed_terms=seed_terms)
    log.info("Scout gathered %d raw signals from %s", len(raw), sources)

    # Replace per-app store reviews with cross-app CATEGORY pains (a pain shared
    # by many apps in a category = a real gap, not one app's bug).
    if config.CATEGORY_PAIN_SYNTHESIS:
        try:
            from agents.category_pain import synthesize as synth_category_pains
            before = len(raw)
            raw = synth_category_pains(raw)
            log.info("Category-pain synthesis: %d signals -> %d", before, len(raw))
        except Exception as e:  # noqa: BLE001 — never block discovery
            log.warning("Category-pain synthesis skipped (%s)", e)

    deduped = _dedup_exact(raw)
    clustered = _cluster(deduped, min_cluster)
    selected = _interleave_by_source(clustered, cap)

    # Distill the final selection into crisp pain statements (one batched LLM
    # call). Bounded to <= cap signals and degrades gracefully to raw content.
    if config.CLUSTER_LABELING and selected:
        from utils.labeler import label_clusters
        selected = label_clusters(selected)

    # Cross-run pain memory: drop pains already evaluated in past runs, so each
    # run explores new ground (compares the crisp labeled pain to history).
    if config.PAIN_MEMORY and selected:
        from utils.pain_memory import filter_novel
        selected, dropped = filter_novel(selected)
        if dropped:
            log.info("Pain memory: dropped %d signal(s) matching already-"
                     "evaluated pains", dropped)

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
