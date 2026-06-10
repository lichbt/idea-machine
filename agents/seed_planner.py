"""Feedback-driven seed planner.

Turns the Scout's app-store search from a static config list into an adaptive
one. It reads verdict history (which past categories PROCEEDed vs KILLed),
then asks the LLM for FRESH category seeds that lean toward winners' neighbours,
avoid saturated losers, and — crucially — avoid categories already tried, so each
run explores new territory instead of re-scraping the same apps (the dedup
deadlock).

Degrades gracefully: any failure (no history, LLM error, malformed output) falls
back to the caller's static base terms, so discovery never breaks.
"""
import logging

import config
from db.models import SwotAnalysis, SwotResearch, ValidatedIdea, get_session
from utils.claude_caller import call_json

log = logging.getLogger(__name__)

_WIN_VERDICTS = ("PROCEED", "PROCEED_WITH_CAUTION")

_SYSTEM = (
    "You are a product-discovery strategist who finds underserved app markets. "
    "Reply with ONLY valid JSON, no prose."
)


def _norm(term):
    return (term or "").strip().lower()


def _history(session):
    """Return (winners, losers, tried) from verdict history.

    winners/losers: lists of (search_keyword, overall_score, demand_score).
    tried: set of normalised category terms already searched (from ALL validated
    ideas, not just analysed ones).
    """
    rows = (session.query(
                SwotAnalysis.verdict,
                SwotAnalysis.overall_score,
                SwotAnalysis.demand_score,
                ValidatedIdea.search_keyword)
            .join(SwotResearch, SwotAnalysis.swot_research_id == SwotResearch.id)
            .join(ValidatedIdea,
                  SwotResearch.validated_idea_id == ValidatedIdea.id)
            .all())
    winners, losers = [], []
    for verdict, score, demand, keyword in rows:
        if not keyword:
            continue
        entry = (keyword.strip(), score, demand)
        if verdict in _WIN_VERDICTS:
            winners.append(entry)
        elif verdict == "KILL":
            losers.append(entry)

    tried = {_norm(kw) for (kw,) in
             session.query(ValidatedIdea.search_keyword).distinct().all()
             if kw}
    return winners, losers, tried


def _fmt(entries, limit):
    """Format '(keyword, score, demand)' rows, best first, capped."""
    seen, lines = set(), []
    for kw, score, demand in sorted(entries, key=lambda e: (e[1] or 0),
                                    reverse=True):
        k = _norm(kw)
        if k in seen:
            continue
        seen.add(k)
        lines.append(f"- {kw} (score={score}, demand={demand})")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "(none yet)"


def _build_prompt(winners, losers, tried, n):
    tried_list = sorted(tried)[: config.FEEDBACK_HISTORY_MAX]
    return f"""We mine app-store complaints to find underserved product markets.
Below is our outcome history. PROCEED categories are promising; KILL categories
were saturated or low-opportunity and should be avoided.

WINNERS (lean toward adjacent problem spaces):
{_fmt(winners, config.FEEDBACK_HISTORY_MAX)}

LOSERS (avoid these and their close neighbours):
{_fmt(losers, config.FEEDBACK_HISTORY_MAX)}

ALREADY TRIED (do NOT return any of these — we need NEW territory):
{", ".join(tried_list) if tried_list else "(none yet)"}

Propose {n} NEW app-store search category phrases (2-4 words each) to discover
underserved apps. Requirements:
- Each must be a real phrase people would type into an app store and that returns
  actual apps (e.g. "expense tracker", "shift scheduler", "inventory manager").
- Favour categories likely to have a LARGE but POORLY-SERVED audience (big market,
  weak incumbents) — that is where the opportunity is.
- Do NOT repeat anything in ALREADY TRIED, and avoid LOSER spaces.
- Mix consumer and small-business/B2B utilities. Be specific, not generic
  ("habit tracker" not "productivity").

Return JSON exactly: {{"seeds": ["...", "..."], "reasoning": "<one sentence>"}}"""


def plan_seeds(n=None, base_terms=None):
    """Return a list of ~n fresh app-store seed terms, or `base_terms` on any
    failure. Generated seeds exclude already-tried categories; if the LLM returns
    too few, the remainder is padded with unused base terms."""
    n = n or config.FEEDBACK_SEED_COUNT
    base_terms = base_terms or []

    session = get_session()
    try:
        winners, losers, tried = _history(session)
    except Exception as e:  # noqa: BLE001 — discovery must never break
        log.warning("Seed history query failed (%s); using static terms", e)
        session.close()
        return base_terms
    finally:
        session.close()

    try:
        result = call_json(_build_prompt(winners, losers, tried, n),
                           system=_SYSTEM)
        raw = result.get("seeds") if isinstance(result, dict) else None
        seeds = []
        seen = set()
        for s in raw or []:
            term = str(s).strip()
            k = _norm(term)
            if not term or k in seen or k in tried:
                continue
            seen.add(k)
            seeds.append(term)
        if result.get("reasoning"):
            log.info("Seed rationale: %s", result["reasoning"])
    except Exception as e:  # noqa: BLE001
        log.warning("Seed generation failed (%s); using static terms", e)
        return base_terms

    if not seeds:
        log.info("Seed planner returned no fresh seeds; using static terms")
        return base_terms

    # Pad with unused base terms if the model came up short.
    for t in base_terms:
        if len(seeds) >= n:
            break
        if _norm(t) not in seen:
            seeds.append(t)
            seen.add(_norm(t))
    return seeds[:n]
