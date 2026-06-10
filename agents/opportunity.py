"""Opportunity Judge — the auto-pilot's go/no-go scorer.

Reads a fully-worked idea (its pain, SWOT verdict/scores, measured demand,
competitors, and the concept) and returns a single 0-100 OPPORTUNITY SCORE
against a fixed rubric, plus a recommendation (PROCEED / ITERATE / DROP) and
reasoning. The `--autopilot` loop uses this to decide when a discovered idea is
good enough to stop and proceed. The score is persisted on the Idea row.
"""
import logging

import config
from db.models import (
    Idea,
    SwotAnalysis,
    SwotResearch,
    ValidatedIdea,
    get_session,
)
from utils.claude_caller import ClaudeJSONError, call_json
from utils.concurrency import pmap

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a ruthless venture scout. You score solo-buildable software "
    "opportunities conservatively against a fixed rubric and never inflate. "
    "Reply with ONLY valid JSON, no prose."
)

_RUBRIC = f"""Score this opportunity 0-100 by summing these criteria (max each):
- pain_intensity (0-20): how acute, frequent, and urgent the pain is.
- market_gap (0-20): how under-served — incumbents weak, absent, or hated.
- real_demand (0-20): evidence real people want this (downloads, ratings, search trend).
- buildability (0-15): can ONE developer ship an MVP in <= 8 weeks.
- monetizability (0-15): clear willingness to pay / a viable model.
- wedge (0-10): a defensible angle or differentiation vs incumbents.

Recommendation rules:
- PROCEED: total >= {config.AUTOPILOT_PROCEED_SCORE} AND no fatal flaw (saturated,
  unbuildable solo, no real demand, or no way to charge).
- ITERATE: promising but needs reframing (wrong audience, weak wedge, thin demand).
- DROP: a fatal flaw makes it not worth pursuing."""


def _prompt(ctx):
    return f"""{_RUBRIC}

OPPORTUNITY DOSSIER:
PAIN: {ctx['pain']}
SWOT VERDICT: {ctx['verdict']} (overall {ctx['overall']}/100, demand {ctx['demand']}/100)
BIGGEST OPPORTUNITY: {ctx['opp']}
BIGGEST RISK: {ctx['risk']}
COMPETITORS: {ctx['competitors']}
CONCEPT: {ctx['concept']}

Return JSON exactly:
{{"opportunity_score": <int 0-100>,
  "recommendation": "PROCEED" | "ITERATE" | "DROP",
  "subscores": {{"pain_intensity": <int>, "market_gap": <int>, "real_demand": <int>,
    "buildability": <int>, "monetizability": <int>, "wedge": <int>}},
  "fatal_flaw": "<short, or empty if none>",
  "reasoning": "<2-3 sentences>"}}"""


def _context(session, idea):
    analysis = session.query(SwotAnalysis).get(idea.swot_analysis_id)
    research = (session.query(SwotResearch).get(analysis.swot_research_id)
                if analysis else None)
    validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                 if research else None)
    comps = []
    for c in (analysis.competitors or [])[:4] if analysis else []:
        if isinstance(c, dict) and c.get("name"):
            comps.append(f"{c['name']} ({(c.get('core_weakness') or '')[:80]})")
    concept = (f"{idea.name}: {idea.oneliner} | features: {idea.core_features} "
               f"| revenue: {idea.revenue_model}")
    return {
        "pain": (validated.pain_point_title if validated else "?"),
        "verdict": (analysis.verdict if analysis else "?"),
        "overall": (analysis.overall_score if analysis else "?"),
        "demand": (analysis.demand_score if analysis else "?"),
        "opp": ((analysis.biggest_opportunity or "")[:200] if analysis else ""),
        "risk": ((analysis.biggest_risk or "")[:200] if analysis else ""),
        "competitors": "; ".join(comps) or "none found",
        "concept": concept[:600],
    }


def _judge(idea_id):
    """Read the idea's context and run the LLM (no DB write). Returns
    (idea_id, result_dict) or None. Safe to call concurrently."""
    session = get_session()
    try:
        idea = session.query(Idea).get(idea_id)
        if not idea:
            return None
        ctx = _context(session, idea)
    finally:
        session.close()
    try:
        result = call_json(_prompt(ctx), system=_SYSTEM)
    except ClaudeJSONError as e:
        log.warning("Opportunity scoring failed for idea %d: %s", idea_id, e)
        return None
    return (idea_id, result)


def _persist(idea_id, result):
    """Write the judge result onto the Idea row. Returns a summary dict."""
    session = get_session()
    try:
        idea = session.query(Idea).get(idea_id)
        if not idea:
            return None
        try:
            sc = int(result.get("opportunity_score") or 0)
        except (TypeError, ValueError):
            sc = 0
        rec = str(result.get("recommendation") or "").upper().strip()
        idea.opportunity_score = sc
        idea.opportunity_recommendation = rec
        idea.opportunity_scores = result.get("subscores")
        idea.opportunity_reasoning = str(result.get("reasoning") or "")
        session.commit()
        out = {"idea_id": idea_id, "name": idea.name, "score": sc,
               "recommendation": rec, "reasoning": idea.opportunity_reasoning,
               "fatal_flaw": str(result.get("fatal_flaw") or "")}
    finally:
        session.close()
    log.info("Opportunity idea %d: %s %d/100 — %s",
             idea_id, out["recommendation"], out["score"], out["name"])
    return out


def score(idea_id):
    """Score one Idea by id and persist the result. Returns a summary dict or
    None on failure."""
    judged = _judge(idea_id)
    return _persist(*judged) if judged else None


def run(idea_ids=None):
    """Score the given ideas (or all unscored ideas if None). Judging runs
    concurrently; writes are sequential. Returns summaries, highest score first."""
    session = get_session()
    try:
        if idea_ids is None:
            idea_ids = [i.id for i in session.query(Idea)
                        .filter(Idea.opportunity_score.is_(None)).all()]
    finally:
        session.close()

    judged = [j for j in pmap(_judge, idea_ids) if j]          # concurrent LLM
    out = [r for r in (_persist(jid, res) for jid, res in judged) if r]  # serial write
    out.sort(key=lambda r: r["score"], reverse=True)
    return out
