"""Agent 5 — Synthesizer.

Turns PROCEED / PROCEED_WITH_CAUTION analyses into concrete product concepts.
Runs a semantic similarity check against existing ideas; if cosine > threshold
it sets similarity_flag and records the matched idea id (still generates the
concept).

KILL verdicts are never passed here (caller filters them).
"""
import logging
from datetime import datetime

import config
from db.models import (
    Idea,
    SwotAnalysis,
    SwotResearch,
    ValidatedIdea,
    get_session,
)
from utils.claude_caller import ClaudeJSONError, call_json
from utils.deduplicator import is_duplicate

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a pragmatic product strategist who designs lean, shippable MVPs "
    "for a solo developer."
)

_PROMPT = """Design a concrete product concept that solves this validated pain
point. It must be buildable by one developer.

PAIN POINT: {pain}
SWOT VERDICT: {verdict} ({score}/100)
BIGGEST OPPORTUNITY: {opportunity}
BIGGEST RISK: {risk}

Return JSON with this exact shape:
{{
  "name": "...",
  "oneliner": "...",
  "core_features": ["feature1", "feature2", "feature3"],
  "tech_stack": "...",
  "revenue_model": "...",
  "build_weeks": 0
}}"""


def _existing_idea_texts(session):
    rows = session.query(Idea).all()
    return rows, [f"{r.name}: {r.oneliner}" for r in rows]


def synthesize(analysis):
    """Generate a product concept for one analysis. Returns the Idea id or None."""
    session = get_session()
    try:
        research = session.query(SwotResearch).get(analysis.swot_research_id)
        validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                     if research else None)
        pain = validated.pain_point_title if validated else "Unknown pain point"

        prompt = _PROMPT.format(
            pain=pain,
            verdict=analysis.verdict,
            score=analysis.overall_score,
            opportunity=analysis.biggest_opportunity or "",
            risk=analysis.biggest_risk or "",
        )
        try:
            concept = call_json(prompt, system=_SYSTEM)
        except ClaudeJSONError as e:
            log.warning("Concept synthesis failed for analysis %d: %s",
                        analysis.id, e)
            return None

        existing_rows, existing_texts = _existing_idea_texts(session)
        concept_text = f"{concept.get('name', '')}: {concept.get('oneliner', '')}"
        flag, idx, score = is_duplicate(concept_text, existing_texts)
        similar_id = existing_rows[idx].id if (flag and idx is not None) else None
        if flag:
            log.info("Concept similar (%.2f) to existing idea %s", score, similar_id)

        idea = Idea(
            swot_analysis_id=analysis.id,
            name=concept.get("name"),
            oneliner=concept.get("oneliner"),
            core_features=concept.get("core_features"),
            tech_stack=concept.get("tech_stack"),
            revenue_model=concept.get("revenue_model"),
            build_weeks=concept.get("build_weeks"),
            similarity_flag=bool(flag),
            similar_idea_id=similar_id,
            created_at=datetime.utcnow(),
        )
        session.add(idea)
        session.commit()
        idea_id = idea.id
    finally:
        session.close()

    log.info("Synthesized idea %d: %s", idea_id, concept.get("name"))
    return idea_id


def run(analysis_ids):
    """Generate concepts for PROCEED / PROCEED_WITH_CAUTION analyses.
    Returns list of Idea ids."""
    out = []
    for aid in analysis_ids:
        session = get_session()
        try:
            analysis = session.query(SwotAnalysis).get(aid)
        finally:
            session.close()
        if not analysis:
            continue
        if analysis.verdict not in ("PROCEED", "PROCEED_WITH_CAUTION"):
            log.info("Skipping synthesis for %s verdict (analysis %d)",
                     analysis.verdict, aid)
            continue
        idea_id = synthesize(analysis)
        if idea_id:
            out.append(idea_id)
    return out
