"""Agent 5 — Synthesizer.

Turns PROCEED / PROCEED_WITH_CAUTION analyses into concrete product concepts.

Diversity guards (so the machine stops emitting near-duplicate concepts):
  - Pain-level dedup: when several analyses target the same pain, only the
    highest-scoring one becomes a concept (the rest are logged + skipped).
  - Existing-idea awareness: the prompt shows the LLM the nearest existing
    concepts and the incumbents' weaknesses, and asks for a meaningfully
    different concept (or a pivot).
  - Active dedup: if the generated concept is still too close to an existing idea
    (cosine > CONCEPT_SIMILARITY_THRESHOLD), it is regenerated once with a
    differentiation instruction before being saved.

Only PROCEED / PROCEED_WITH_CAUTION analyses are turned into concepts (KILLs are
filtered out here and by the DB-driven selection).
"""
import logging
from datetime import datetime

from sqlalchemy import exists

import config
from db.models import (
    Idea,
    SwotAnalysis,
    SwotResearch,
    ValidatedIdea,
    get_session,
)
from utils.claude_caller import ClaudeJSONError, call_json
from utils.deduplicator import is_duplicate, most_similar, top_similar

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a pragmatic product strategist who designs lean, shippable MVPs "
    "for a solo developer. You avoid generic me-too concepts and always carve a "
    "specific, defensible wedge."
)

_PROMPT = """Design a concrete product concept that solves this validated pain
point. It must be buildable by one developer, and it must be DIFFERENTIATED — not
a generic clone of what already exists.

PAIN POINT: {pain}
SWOT VERDICT: {verdict} ({score}/100)
BIGGEST OPPORTUNITY: {opportunity}
BIGGEST RISK: {risk}
{swot_block}{competitor_block}{complaint_block}{existing_block}
Design guidance:
- Attack a SPECIFIC wedge the incumbents above fail at (reference which weakness).
- It must be meaningfully different from the EXISTING CONCEPTS listed; if the
  space is already covered, pivot to an unaddressed sub-angle or audience.
- Prefer a concrete niche + a non-obvious monetization over a broad generic app.

Return JSON with this exact shape:
{{
  "name": "...",
  "oneliner": "...",
  "core_features": ["feature1", "feature2", "feature3"],
  "tech_stack": "...",
  "revenue_model": "...",
  "build_weeks": 0
}}"""


# ── context blocks (all degrade to "" when data is absent) ─────────────────
def _prose(quadrant):
    """Pull a short prose summary out of a SWOT quadrant (dict with 'prose',
    or a plain string)."""
    if isinstance(quadrant, dict):
        return (quadrant.get("prose") or "").strip()
    if isinstance(quadrant, str):
        return quadrant.strip()
    return ""


def _swot_block(analysis):
    bits = []
    for label, q in (("STRENGTH", analysis.strengths),
                     ("WEAKNESS", analysis.weaknesses),
                     ("THREAT", analysis.threats)):
        prose = _prose(q)
        if prose:
            bits.append(f"{label}: {prose[:240]}")
    return ("\n" + "\n".join(bits) + "\n") if bits else ""


def _competitor_block(analysis):
    lines = []
    for c in (analysis.competitors or [])[:4]:
        if not isinstance(c, dict):
            continue
        name = (c.get("name") or "").strip()
        if not name:
            continue
        weak = (c.get("core_weakness") or "").strip()
        lines.append(f"- {name}: {weak[:160]}" if weak else f"- {name}")
    if not lines:
        return ""
    return ("\nEXISTING COMPETITORS (and where they fail):\n"
            + "\n".join(lines) + "\n")


def _complaint_block(analysis):
    dd = analysis.demand_data if isinstance(analysis.demand_data, dict) else {}
    snippets = []
    for app in (dd.get("prior_apps") or []):
        if not isinstance(app, dict):
            continue
        for rev in (app.get("reviews") or []):
            try:
                rating = int(rev.get("rating", 5))
            except (TypeError, ValueError, AttributeError):
                continue
            if rating > 2:
                continue
            text = (rev.get("text") or "").strip().replace("\n", " ")
            if text:
                snippets.append(f'- "{text[:160]}"')
            if len(snippets) >= 3:
                break
        if len(snippets) >= 3:
            break
    if not snippets:
        return ""
    return ("\nUNSOLVED COMPLAINTS (from real low-star reviews):\n"
            + "\n".join(snippets) + "\n")


def _existing_block(neighbor_texts):
    if not neighbor_texts:
        return ""
    lines = "\n".join(f"- {t}" for t in neighbor_texts)
    return ("\nEXISTING CONCEPTS we already have (do NOT duplicate — differentiate "
            "or pivot):\n" + lines + "\n")


def _existing_idea_texts(session):
    rows = session.query(Idea).all()
    return rows, [f"{r.name}: {r.oneliner}" for r in rows]


def _concept_text(concept):
    return f"{concept.get('name', '')}: {concept.get('oneliner', '')}"


def _generate(prompt):
    try:
        return call_json(prompt, system=_SYSTEM)
    except ClaudeJSONError as e:
        log.warning("Concept synthesis failed: %s", e)
        return None


# ── per-analysis concept generation ────────────────────────────────────────
def synthesize(analysis):
    """Generate a differentiated product concept for one analysis. Returns the
    Idea id or None."""
    session = get_session()
    try:
        research = session.query(SwotResearch).get(analysis.swot_research_id)
        validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                     if research else None)
        pain = validated.pain_point_title if validated else "Unknown pain point"

        existing_rows, existing_texts = _existing_idea_texts(session)
        neighbors = [existing_texts[i] for i, _ in
                     top_similar(pain, existing_texts, config.CONCEPT_NEIGHBORS)]

        base_prompt = _PROMPT.format(
            pain=pain,
            verdict=analysis.verdict,
            score=analysis.overall_score,
            opportunity=analysis.biggest_opportunity or "",
            risk=analysis.biggest_risk or "",
            swot_block=_swot_block(analysis),
            competitor_block=_competitor_block(analysis),
            complaint_block=_complaint_block(analysis),
            existing_block=_existing_block(neighbors),
        )

        concept = _generate(base_prompt)
        if concept is None:
            return None

        # Active dedup: regenerate (bounded) while the concept is too close to an
        # existing idea, using the lower concept-specific threshold.
        flag, idx, score = is_duplicate(
            _concept_text(concept), existing_texts,
            threshold=config.CONCEPT_SIMILARITY_THRESHOLD)
        attempts = 0
        while flag and attempts < config.CONCEPT_REGEN_MAX:
            attempts += 1
            dup = existing_texts[idx] if idx is not None else "an existing idea"
            log.info("Concept too similar (%.2f) to '%s'; regenerating (%d/%d)",
                     score, dup[:40], attempts, config.CONCEPT_REGEN_MAX)
            retry = _generate(base_prompt + (
                f'\n\nYour previous concept was TOO SIMILAR to: "{dup}". Produce a '
                "clearly DIFFERENT concept — change the wedge, audience, or business "
                "model. Do not restate the same product."))
            if retry is None:
                break
            concept = retry
            flag, idx, score = is_duplicate(
                _concept_text(concept), existing_texts,
                threshold=config.CONCEPT_SIMILARITY_THRESHOLD)

        similar_id = existing_rows[idx].id if (flag and idx is not None) else None
        if flag:
            log.info("Concept still similar (%.2f) to idea %s after %d regen; "
                     "keeping flagged", score, similar_id, attempts)

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


# ── pain-level dedup ────────────────────────────────────────────────────────
def _pain_for(session, analysis):
    research = session.query(SwotResearch).get(analysis.swot_research_id)
    validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                 if research else None)
    return (validated.pain_point_title if validated else "") or ""


def _dedup_by_pain(items):
    """items: list of (analysis_id, score, pain). Greedy-cluster by pain
    similarity (highest score first becomes the cluster representative). Returns
    (kept_ids, skipped) where skipped is [(skipped_id, kept_id)]."""
    kept = []  # (analysis_id, pain)
    kept_ids = []
    skipped = []
    for aid, score, pain in sorted(items, key=lambda t: (t[1] or 0), reverse=True):
        rep_pains = [p for _, p in kept]
        idx, sim = (most_similar(pain, rep_pains) if (rep_pains and pain)
                    else (None, 0.0))
        if idx is not None and sim > config.CONCEPT_SIMILARITY_THRESHOLD:
            skipped.append((aid, kept[idx][0]))
        else:
            kept.append((aid, pain))
            kept_ids.append(aid)
    return kept_ids, skipped


def run(analysis_ids=None):
    """Generate concepts for PROCEED / PROCEED_WITH_CAUTION analyses.

    When analysis_ids is None, selects non-KILL analyses that have no Idea yet
    (DB-driven, resumable). Analyses targeting the same pain are collapsed to the
    highest-scoring one. Returns list of Idea ids.
    """
    session = get_session()
    try:
        if analysis_ids is None:
            analyses = (session.query(SwotAnalysis)
                        .filter(SwotAnalysis.verdict.in_(
                            ["PROCEED", "PROCEED_WITH_CAUTION"]))
                        .filter(~exists().where(
                            Idea.swot_analysis_id == SwotAnalysis.id))
                        .order_by(SwotAnalysis.overall_score.desc())
                        .all())
        else:
            analyses = (session.query(SwotAnalysis)
                        .filter(SwotAnalysis.id.in_(analysis_ids)).all())
        eligible = []
        for a in analyses:
            if a.verdict not in ("PROCEED", "PROCEED_WITH_CAUTION"):
                log.info("Skipping synthesis for %s verdict (analysis %d)",
                         a.verdict, a.id)
                continue
            eligible.append((a.id, a.overall_score, _pain_for(session, a)))
    finally:
        session.close()

    kept_ids, skipped = _dedup_by_pain(eligible)
    for sid, kid in skipped:
        log.info("pain-dup: skipping analysis %d — same pain as analysis %d",
                 sid, kid)

    out = []
    for aid in kept_ids:
        session = get_session()
        try:
            analysis = session.query(SwotAnalysis).get(aid)
        finally:
            session.close()
        if not analysis:
            continue
        idea_id = synthesize(analysis)
        if idea_id:
            out.append(idea_id)
    return out
