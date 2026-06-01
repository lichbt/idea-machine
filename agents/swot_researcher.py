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

import config
from db.models import SwotResearch, ValidatedIdea, get_session
from utils import demand

log = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"


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
            hits = _serper(q)
            results.append({"query": q, "results": hits})
            any_success = True
        except requests.RequestException as e:
            log.warning("Serper query failed ('%s'): %s", q, e)
            results.append({"query": q, "results": [], "error": str(e)})
    return results, any_success


def research(validated_idea):
    """Run Pass 1 for one validated idea. Returns the SwotResearch id.

    Always writes a row before returning. research_status is one of:
    complete / partial / failed.
    """
    pain = validated_idea.pain_point_title

    strengths_q = [
        f"{pain} reddit complaints site:reddit.com",
        f"{pain} tool site:producthunt.com",
    ]
    weaknesses_q = [
        f"{pain} tool failed shut down",
        f"{pain} API dependency integration required",
    ]
    opportunities_q = [
        f"{pain} use case adjacent industries",
    ]
    threats_q = [
        f"{pain} software tool pricing",
        f"{pain} reviews G2 Capterra",
        f"{pain} Notion Slack Google feature",
    ]
    market_q = [
        f"{pain} market size USD",
        f"{pain} industry growth rate forecast",
        f"{pain} number of users statistics",
    ]

    strengths, s_ok = _run_queries(strengths_q)
    weaknesses, w_ok = _run_queries(weaknesses_q)
    opp_results, o_ok = _run_queries(opportunities_q)
    threats, t_ok = _run_queries(threats_q)
    market_results, _m_ok = _run_queries(market_q)

    # Idea-specific demand: pain-specific app search (apps that already tried to
    # fix this pain) + their reviews, plus Google Trends on the short category
    # keyword (narrow pain phrases never return trend data). Reuse its trend call
    # for the opportunities/market evidence so pytrends is hit once per idea.
    keyword = _keyword_for(validated_idea)
    queries = getattr(validated_idea, "app_search_queries", None) or []
    demand_signal = demand.measure(keyword, queries=queries)
    trend = demand_signal.get("trend") or {"status": "unavailable"}
    opportunities = {"trend_data": trend, "search": opp_results}
    market = {
        "keyword": keyword,
        "demand": demand_signal,
        "trend_data": trend,
        "search": market_results,
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


def run(validated_idea_ids):
    """Run Pass 1 for each id. Returns list of (swot_research_id, status)."""
    session = get_session()
    try:
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
