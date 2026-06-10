"""Agent 2 — Validator.

Scores each pending raw signal on four axes (0-25 each, max 100). Signals at or
above VALIDATION_THRESHOLD pass. Only the top MAX_SWOT_PER_RUN passing signals
proceed to SWOT (cost cap).

Resilience: a signal whose Claude call fails after retries is marked
validation_failed and skipped — the pipeline continues.
"""
import logging
from datetime import datetime

import config
from db.models import RawSignal, ValidatedIdea, get_session
from utils.claude_caller import ClaudeJSONError, call_json
from utils.concurrency import pmap

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a ruthless startup analyst scoring pain points scraped from the web. "
    "Score conservatively; most ideas are mediocre."
)

_PROMPT = """Score this pain point signal on four axes, each 0-25 (total max 100):

- pain_intensity: urgency and frustration in the language (0-25)
- market_gap: absence of a dominant existing solution (0-25)
- buildability: can ONE developer ship an MVP in <= 8 weeks (0-25)
- monetizability: clear willingness-to-pay signals (0-25)

If the signal header includes a rating or review count (e.g. "12,345 ratings"
or "895 reviews"), treat it as a market-size proxy: a high count means a large,
validated market, so a genuine complaint there is worth more on market_gap and
monetizability. A high "low-star" count signals unmet demand worth addressing.

SIGNAL SOURCE: {source}
SIGNAL URL: {url}
SIGNAL CONTENT:
\"\"\"
{content}
\"\"\"

Also produce a SHORT search keyword (2-3 words) describing the product
CATEGORY a user would type into an app store or Google to find a solution —
e.g. "habit tracker", "invoice app", "team chat". Generic and category-level,
NOT the full pain sentence. This drives a Google Trends lookup, so it must be a
term people actually search.

Also produce app_search_queries: 3-5 SHORT (2-4 word) app-store search phrases
that target this SPECIFIC pain, used to find apps that already TRIED to solve it.
Be more specific than the category keyword — encode the actual problem, not just
the space. E.g. for "habit apps lose my streak when I reinstall":
["habit tracker backup", "habit streak cloud sync", "habit tracker restore data"].
Each phrase must be short enough that an app store returns results (no full
sentences) yet specific enough to surface prior attempts at THIS pain.

Return JSON with this exact shape:
{{
  "pain_point_title": "<concise title of the underlying pain point>",
  "search_keyword": "<2-3 word app-store / search category term>",
  "app_search_queries": ["<2-4 word pain-specific phrase>", "..."],
  "scores": {{
    "pain_intensity": <int>,
    "market_gap": <int>,
    "buildability": <int>,
    "monetizability": <int>
  }},
  "reasoning": "<one sentence>"
}}"""


def _score_fields(source, url, content):
    prompt = _PROMPT.format(source=source, url=url or "",
                            content=(content or "")[:4000])
    return call_json(prompt, system=_SYSTEM)


def _score_signal(signal):
    return _score_fields(signal.source, signal.url, signal.content)


def run(threshold=None, swot_cap=None):
    """Validate all pending signals. Returns list of ValidatedIdea ids that
    passed and are selected for SWOT (capped, highest score first).

    The per-signal LLM scoring runs concurrently; the DB writes stay on the main
    thread (read pending -> score in parallel -> write sequentially)."""
    threshold = config.VALIDATION_THRESHOLD if threshold is None else threshold
    swot_cap = config.MAX_SWOT_PER_RUN if swot_cap is None else swot_cap

    session = get_session()
    try:
        items = [(s.id, s.source, s.url, s.content)
                 for s in session.query(RawSignal).filter_by(status="pending").all()]
    finally:
        session.close()
    log.info("Validator scoring %d pending signals", len(items))

    def _score(item):
        sid, source, url, content = item
        try:
            return _score_fields(source, url, content)
        except ClaudeJSONError as e:
            log.warning("Validation failed for signal %d: %s", sid, e)
            return None

    results = pmap(_score, items)  # aligned with items; None = failed

    session = get_session()
    passed_records = []  # (total_score, validated_idea_id)
    try:
        for (sid, _src, _url, _content), result in zip(items, results):
            signal = session.query(RawSignal).get(sid)
            if signal is None:
                continue
            if result is None:
                signal.status = "validation_failed"
                continue
            scores = result.get("scores", {})
            total = sum(int(scores.get(k, 0)) for k in
                        ("pain_intensity", "market_gap",
                         "buildability", "monetizability"))
            passed = total >= threshold
            vi = ValidatedIdea(
                signal_id=sid,
                pain_point_title=result.get("pain_point_title", "Untitled"),
                search_keyword=result.get("search_keyword", ""),
                app_search_queries=result.get("app_search_queries", []),
                scores=scores,
                total_score=total,
                passed=passed,
                validated_at=datetime.utcnow(),
            )
            session.add(vi)
            session.flush()  # assign vi.id
            signal.status = "validated" if passed else "insufficient"
            if passed:
                passed_records.append((total, vi.id))
        session.commit()
    finally:
        session.close()

    passed_records.sort(reverse=True)
    selected = [vid for _, vid in passed_records[:swot_cap]]
    log.info("Validator: %d passed, %d selected for SWOT",
             len(passed_records), len(selected))
    return selected
