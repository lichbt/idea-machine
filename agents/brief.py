"""Build-readiness brief.

Turns a validated, judged idea into a concrete MVP plan a solo developer could
start tomorrow — scope, first features, stack, week-by-week steps, the wedge,
landing-page copy, first users, and de-risking. One LLM call. The brief is
persisted on the Idea (`build_brief`) and rendered to a markdown file.
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

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a pragmatic technical co-founder who turns a validated idea into a "
    "concrete, buildable MVP plan for a solo developer. Be specific and realistic. "
    "Reply with ONLY valid JSON, no prose."
)

_PROMPT = """Turn this validated product idea into a BUILD BRIEF a solo developer
could start on tomorrow. Be concrete; an MVP must be shippable in <= 8 weeks.

IDEA: {name} — {oneliner}
PAIN: {pain}
CORE FEATURES (from concept): {features}
REVENUE MODEL: {revenue}
SWOT VERDICT: {verdict} (overall {overall}/100, demand {demand}/100, opportunity {opp}/100)
BIGGEST OPPORTUNITY: {opportunity}
BIGGEST RISK: {risk}
COMPETITORS: {competitors}

Return JSON exactly:
{{
  "mvp_scope": "1-2 sentences: the smallest thing worth shipping",
  "first_features": ["3-5 v1 features, in build order"],
  "tech_stack": "a concrete stack a solo dev can ship fast",
  "build_steps": ["milestone steps to an MVP in <= 8 weeks"],
  "wedge": "the specific angle vs the incumbents above",
  "landing_headline": "a punchy landing-page headline",
  "landing_subcopy": "1-2 sentence sub-headline",
  "first_users": "where to find the first 10 users",
  "top_risks": ["2-3 biggest risks, each with how to de-risk it"]
}}"""


def _context(session, idea):
    analysis = session.query(SwotAnalysis).get(idea.swot_analysis_id)
    research = (session.query(SwotResearch).get(analysis.swot_research_id)
                if analysis else None)
    validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                 if research else None)
    comps = []
    for c in (analysis.competitors or [])[:4] if analysis else []:
        if isinstance(c, dict) and c.get("name"):
            comps.append(f"{c['name']} ({(c.get('core_weakness') or '')[:70]})")
    return {
        "name": idea.name or "Untitled",
        "oneliner": idea.oneliner or "",
        "pain": (validated.pain_point_title if validated else "?"),
        "features": idea.core_features or [],
        "revenue": idea.revenue_model or "",
        "verdict": (analysis.verdict if analysis else "?"),
        "overall": (analysis.overall_score if analysis else "?"),
        "demand": (analysis.demand_score if analysis else "?"),
        "opp": (idea.opportunity_score if idea.opportunity_score is not None else "?"),
        "opportunity": ((analysis.biggest_opportunity or "")[:200] if analysis else ""),
        "risk": ((analysis.biggest_risk or "")[:200] if analysis else ""),
        "competitors": "; ".join(comps) or "none found",
    }


def _markdown(name, brief):
    def section(title, body):
        return f"## {title}\n\n{body}\n"

    def bullets(items):
        return "\n".join(f"- {i}" for i in (items or [])) or "—"

    return "\n".join([
        f"# Build Brief — {name}\n",
        section("MVP scope", brief.get("mvp_scope", "—")),
        section("First features (build order)", bullets(brief.get("first_features"))),
        section("Tech stack", brief.get("tech_stack", "—")),
        section("Build steps (≤ 8 weeks)", bullets(brief.get("build_steps"))),
        section("Wedge", brief.get("wedge", "—")),
        section("Landing page",
                f"**{brief.get('landing_headline', '')}**\n\n"
                f"{brief.get('landing_subcopy', '')}"),
        section("First 10 users", brief.get("first_users", "—")),
        section("Top risks & de-risking", bullets(brief.get("top_risks"))),
    ])


def generate(idea_id):
    """Generate + persist a build brief for one Idea. Returns (path, brief) or
    (None, None) on failure."""
    session = get_session()
    try:
        idea = session.query(Idea).get(idea_id)
        if not idea:
            log.warning("Brief: idea %d not found", idea_id)
            return None, None
        ctx = _context(session, idea)
        name = ctx["name"]
        try:
            brief = call_json(_PROMPT.format(**ctx), system=_SYSTEM)
        except ClaudeJSONError as e:
            log.warning("Brief generation failed for idea %d: %s", idea_id, e)
            return None, None
        idea.build_brief = brief
        session.commit()
    finally:
        session.close()

    md = _markdown(name, brief)
    safe = "".join(c if c.isalnum() else "_" for c in name)[:40]
    path = config.BASE_DIR / "reports" / f"brief_{idea_id}_{safe}.md"
    path.parent.mkdir(exist_ok=True)
    path.write_text(md, encoding="utf-8")
    log.info("Build brief for idea %d (%s) -> %s", idea_id, name, path)
    return str(path), brief


def best_idea_id():
    """The id of the highest-opportunity idea (prefers ones with a score)."""
    session = get_session()
    try:
        idea = (session.query(Idea)
                .filter(Idea.opportunity_score.isnot(None))
                .order_by(Idea.opportunity_score.desc())
                .first())
        if not idea:
            idea = session.query(Idea).order_by(Idea.id.desc()).first()
        return idea.id if idea else None
    finally:
        session.close()
