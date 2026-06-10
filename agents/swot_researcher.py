"""Agent 3 — SWOT Researcher (Pass 1).

Gathers raw evidence for all four SWOT quadrants via Serper web search and
pytrends. ALWAYS persists a swot_research row before Pass 2 is invoked.

Fallbacks:
  - pytrends fails        -> trend_data = "unavailable", research continues.
  - Serper down entirely  -> research_status = "failed", row saved, NOT advanced
                             to Pass 2 (caller skips synthesis, retries later).
"""
import logging
from datetime import datetime

import requests
from sqlalchemy import exists

import config
from db.models import SwotResearch, ValidatedIdea, get_session
from utils import demand
from utils.claude_caller import ClaudeJSONError, call_json
from utils.search import web_search

log = logging.getLogger(__name__)


def _keyword_for(validated_idea):
    """Short demand-lookup keyword. Prefer the validator's search_keyword; fall
    back to the first few words of the pain title for older rows."""
    kw = (getattr(validated_idea, "search_keyword", "") or "").strip()
    if kw:
        return kw
    words = (validated_idea.pain_point_title or "").split()
    return " ".join(words[:3])


def _serper(query, num=10):
    """Run one Serper query. Returns list of {title, link, snippet}.
    Raises requests.RequestException on transport failure (caller decides)."""
    resp = requests.post(
        _SERPER_URL,
        headers={"X-API-KEY": config.SERPER_API_KEY,
                 "Content-Type": "application/json"},
        json={"q": query, "num": num},
        timeout=20,
    )
    resp.raise_for_status()
    data = resp.json()
    out = []
    for item in data.get("organic", []):
        out.append({
            "title": item.get("title"),
            "link": item.get("link"),
            "snippet": item.get("snippet"),
        })
    return out


def _run_queries(queries):
    """Run a list of queries. Returns (results, any_success).
    Individual query failures are tolerated; transport is retried per-query."""
    results = []
    any_success = False
    for q in queries:
        try:
            hits = web_search(q)
            results.append({"query": q, "results": hits})
            any_success = True
        except requests.RequestException as e:
            log.warning("Web search failed ('%s'): %s", q, e)
            results.append({"query": q, "results": [], "error": str(e)})
    return results, any_success


_QUERY_SYSTEM = (
    "You write precise Google search queries to research whether to build a "
    "software product. Reply with ONLY valid JSON, no prose."
)
_QUERY_GROUPS = ("strengths", "weaknesses", "opportunities", "threats",
                 "market", "competitors")


def _plan_queries(pain, keyword):
    """LLM-tailored, idea-specific search queries per quadrant. Returns a dict
    group -> [queries], or None on failure (caller falls back to templates)."""
    prompt = f"""We are deciding whether to build a product for this pain.
PAIN: {pain}
CATEGORY: {keyword}

Write SHARP, SPECIFIC Google search queries (3-8 words, no quotes) to gather SWOT
evidence. Tailor them to THIS pain — not generic templates. Return JSON exactly:
{{"strengths": ["find demand/validation that people want this"],
  "weaknesses": ["find why this is hard, or tools that failed at it"],
  "opportunities": ["find adjacent uses / growth / timing"],
  "threats": ["find risks, incumbents adding this feature"],
  "market": ["find market size, growth rate, user counts"],
  "competitors": ["find existing products/tools/alternatives, incl. github/open source"]}}
Each list has 1-3 queries."""
    try:
        result = call_json(prompt, system=_QUERY_SYSTEM)
    except ClaudeJSONError as e:
        log.warning("Query planning failed (%s); using templates", e)
        return None
    if not isinstance(result, dict):
        return None
    out = {}
    for g in _QUERY_GROUPS:
        qs = [str(q).strip() for q in (result.get(g) or []) if str(q).strip()]
        if qs:
            out[g] = qs[:3]
    return out or None


def research(validated_idea):
    """Run Pass 1 for one validated idea. Returns the SwotResearch id.

    Always writes a row before returning. research_status is one of:
    complete / partial / failed.
    """
    pain = validated_idea.pain_point_title
    keyword = _keyword_for(validated_idea)

    # Tailored, idea-specific queries; fall back to templated `pain + suffix`.
    planned = _plan_queries(pain, keyword) if config.SWOT_PLAN_QUERIES else None
    planned = planned or {}

    strengths_q = planned.get("strengths") or [
        f"{pain} reddit complaints site:reddit.com",
        f"{pain} tool site:producthunt.com",
    ]
    weaknesses_q = planned.get("weaknesses") or [
        f"{pain} tool failed shut down",
        f"{pain} API dependency integration required",
    ]
    opportunities_q = planned.get("opportunities") or [
        f"{pain} use case adjacent industries",
    ]
    threats_q = planned.get("threats") or [
        f"{pain} software tool pricing",
        f"{pain} reviews G2 Capterra",
        f"{pain} Notion Slack Google feature",
    ]
    market_q = planned.get("market") or [
        f"{pain} market size USD",
        f"{pain} industry growth rate forecast",
        f"{pain} number of users statistics",
    ]
    # Real competitor research — web/GitHub, not just app-store prior-art.
    competitors_q = planned.get("competitors") or [
        f"{keyword} alternatives",
        f"best {keyword} tools",
        f"{pain} open source github",
    ]

    strengths, s_ok = _run_queries(strengths_q)
    weaknesses, w_ok = _run_queries(weaknesses_q)
    opp_results, o_ok = _run_queries(opportunities_q)
    threats, t_ok = _run_queries(threats_q)
    market_results, _m_ok = _run_queries(market_q)
    competitor_results, _c_ok = _run_queries(competitors_q)

    # Idea-specific demand: pain-specific app search (apps that already tried to
    # fix this pain) + their reviews, plus Google Trends on the short category
    # keyword (narrow pain phrases never return trend data). Reuse its trend call
    # for the opportunities/market evidence so pytrends is hit once per idea.
    queries = getattr(validated_idea, "app_search_queries", None) or []
    demand_signal = demand.measure(keyword, queries=queries)
    trend = demand_signal.get("trend") or {"status": "unavailable"}
    opportunities = {"trend_data": trend, "search": opp_results}
    market = {
        "keyword": keyword,
        "demand": demand_signal,
        "trend_data": trend,
        "search": market_results,
        "competitors_search": competitor_results,  # real competitor evidence
    }

    # Completeness reflects search evidence only. Google Trends (pytrends) is
    # optional and frequently unavailable, so it must not gate completeness or
    # it would tax every idea via the reliability penalty.
    serper_any = any([s_ok, w_ok, o_ok, t_ok])
    if not serper_any:
        status = "failed"
    elif all([s_ok, w_ok, o_ok, t_ok]):
        status = "complete"
    else:
        status = "partial"

    session = get_session()
    try:
        row = SwotResearch(
            validated_idea_id=validated_idea.id,
            strengths_raw=strengths,
            weaknesses_raw=weaknesses,
            opportunities_raw=opportunities,
            threats_raw=threats,
            market_raw=market,
            research_status=status,
            researched_at=datetime.utcnow(),
        )
        session.add(row)
        session.commit()
        row_id = row.id
    finally:
        session.close()

    log.info("SWOT research for idea %d -> status=%s (id=%d)",
             validated_idea.id, status, row_id)
    return row_id


def run(validated_idea_ids=None):
    """Run Pass 1. Returns list of (swot_research_id, status).

    When validated_idea_ids is None, selects its own work from the DB: passing
    ValidatedIdea rows that have no SwotResearch yet (resumable/idempotent),
    highest score first, capped at MAX_SWOT_PER_RUN. This reconstructs the
    validator's old top-N selection from persisted state, so the stage can run
    standalone (e.g. `run.py --research`). An explicit id list keeps the old
    behaviour for the in-process pipeline path.
    """
    session = get_session()
    try:
        if validated_idea_ids is None:
            ideas = (session.query(ValidatedIdea)
                     .filter(ValidatedIdea.passed.is_(True))
                     .filter(~exists().where(
                         SwotResearch.validated_idea_id == ValidatedIdea.id))
                     .order_by(ValidatedIdea.total_score.desc())
                     .limit(config.MAX_SWOT_PER_RUN)
                     .all())
            log.info("SWOT research (DB-driven): %d unresearched idea(s) selected",
                     len(ideas))
        else:
            ideas = (session.query(ValidatedIdea)
                     .filter(ValidatedIdea.id.in_(validated_idea_ids)).all())
    finally:
        session.close()

    out = []
    for idea in ideas:
        rid = research(idea)
        # re-read status cheaply
        s = get_session()
        try:
            status = s.query(SwotResearch).get(rid).research_status
        finally:
            s.close()
        out.append((rid, status))
    return out
