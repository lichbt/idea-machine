"""Agent 4 — SWOT Synthesizer (Pass 2).

Takes a raw-evidence bundle and produces a structured SWOT with per-quadrant
scores/confidence, competitor cards, weighted overall score, reliability
penalty, and a verdict.

Invariants:
  - Never names a competitor without a source URL present in the evidence.
  - Skips items whose Pass-1 status is "failed" (handled by caller).
"""
import logging
from datetime import datetime

import config
from db.models import SwotAnalysis, SwotResearch, ValidatedIdea, get_session
from utils.claude_caller import ClaudeJSONError, call_json

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are an evidence-disciplined market analyst. You cite sources for every "
    "claim and never invent facts or competitors."
)

_PROMPT = """Synthesize a structured SWOT analysis for this product pain point
using ONLY the evidence provided. Rules:

1. Only name competitors for which a source URL appears in the evidence. Do NOT
   invent competitors.
2. If no competitors are found after thorough search, score Threats HIGH (a
   benign threat landscape is favorable) and flag as a potential blue ocean.
   Also note low competition may mean an unvalidated market.
3. Cite evidence URLs for every claim. Do not reason from general knowledge alone.
4. MARKET ANALYSIS: ground your read in the DEMAND_SIGNAL first — it holds the
   REAL, idea-specific demand measured for this idea's category (App Store rating
   counts, Play Store install counts, Google Trends direction). Quote those
   concrete numbers (installs, ratings, trend %) in your summary. Use MARKET_RAW
   web figures only as secondary TAM context. If a figure is absent, set it to
   "unknown" — do NOT invent or guess. A low demand_score (few downloads, no
   search interest) means few people want this — say so plainly even if the rest
   of the SWOT reads positive.
5. PRIOR_ATTEMPTS lists real apps that ALREADY tried to solve this exact pain,
   with their store traction and a sample of (low-star-biased) user reviews.
   - Treat these as your PRIMARY competitor set: every competitor you name should
     come from PRIOR_ATTEMPTS (or MARKET_RAW), and you MUST copy its store URL
     into source_url. Never invent a competitor.
   - Read the reviews to judge whether the pain is STILL UNSOLVED. Persistent
     complaints about the very pain in question = a real opening (score
     Opportunities higher, Threats higher since incumbents are weak). High ratings
     with no relevant complaints = the pain is already well served (Threats lower,
     and a new entrant's Strengths lower). Quote a representative review in the
     relevant quadrant's prose.
   - If PRIOR_ATTEMPTS is empty, nobody has shipped for this pain: possible blue
     ocean OR no demand — weigh against the DEMAND_SIGNAL before concluding.

SCORING (critical):
- Every quadrant "score" is an integer from 0 to 100.
- Score each quadrant as FAVORABILITY to pursuing this product: a HIGHER score is
  always BETTER for the venture, in all four quadrants.
  - strengths: 100 = exceptionally strong problem–market fit; 0 = no real signal.
  - opportunities: 100 = large, growing, well-timed opportunity; 0 = none.
  - weaknesses: 100 = weaknesses are trivial/easily overcome; 0 = severe,
    structural weaknesses that likely sink the product.
  - threats: 100 = benign landscape, little competition or risk; 0 = brutal,
    crowded, incumbent-dominated, or existentially risky.
- Use the full 0-100 range; calibrate so a typical mediocre idea lands near 50.

PAIN POINT: {pain}

DEMAND_SIGNAL (measured app downloads + search trend for this idea): {demand}

PRIOR_ATTEMPTS (apps that already tried this pain, with traction + reviews): {prior}

EVIDENCE BUNDLE (JSON):
STRENGTHS_RAW: {strengths}
WEAKNESSES_RAW: {weaknesses}
OPPORTUNITIES_RAW: {opportunities}
THREATS_RAW: {threats}
MARKET_RAW: {market}

Return JSON with this exact shape (each quadrant identical structure; "score" is
an integer 0-100 where higher is always more favorable, per the rules above):
{{
  "strengths":     {{"prose": "...", "score": <0-100>, "score_label": "...", "confidence": "High|Medium|Low", "confidence_reason": "...", "evidence": ["url"]}},
  "weaknesses":    {{"prose": "...", "score": <0-100>, "score_label": "...", "confidence": "High|Medium|Low", "confidence_reason": "...", "evidence": ["url"]}},
  "opportunities": {{"prose": "...", "score": <0-100>, "score_label": "...", "confidence": "High|Medium|Low", "confidence_reason": "...", "evidence": ["url"]}},
  "threats":       {{"prose": "...", "score": <0-100>, "score_label": "...", "confidence": "High|Medium|Low", "confidence_reason": "...", "evidence": ["url"]}},
  "competitors": [
    {{"name": "...", "pricing": "...", "traction": "...", "core_weakness": "...", "big_player_risk": false, "source_url": "..."}}
  ],
  "market_analysis": {{"market_size": "$ figure or unknown", "tam": "total addressable market or unknown", "growth_trend": "growing/flat/declining + rate if known", "summary": "1-2 sentence market read", "evidence": ["url"]}},
  "biggest_risk": "...",
  "biggest_opportunity": "...",
  "verdict_reasoning": "..."
}}"""


def _weighted_score(quadrants):
    total = 0.0
    for name, weight in config.SWOT_WEIGHTS.items():
        q = quadrants.get(name) or {}
        try:
            total += float(q.get("score", 0)) * weight
        except (TypeError, ValueError):
            pass
    return round(total)


def _data_missing(research_row):
    """True if search evidence was incomplete (drives the reliability penalty).
    Trend data is optional/flaky, so its absence alone is not penalized."""
    return research_row.research_status in ("partial", "failed")


def _verdict(score):
    if score >= config.SWOT_PROCEED_THRESHOLD:
        return "PROCEED"
    if score >= config.SWOT_CAUTION_THRESHOLD:
        return "PROCEED_WITH_CAUTION"
    return "KILL"


_VERDICT_RANK = {"KILL": 0, "PROCEED_WITH_CAUTION": 1, "PROCEED": 2}


def _apply_demand_gate(verdict, demand):
    """Cap the verdict by measured demand. An idea nobody downloads or searches
    for is not worth following, however good the SWOT prose. Only gates when
    demand is actually measurable (apps found on a store); a non-measurable
    result (possible blue ocean) is left to the qualitative SWOT.

    Returns (verdict, reason). reason is "" when no gate was applied.
    """
    if not demand or not demand.get("measurable"):
        return verdict, ""
    score = demand.get("demand_score", 0)
    band = demand.get("demand_band", "?")
    if score < config.DEMAND_KILL_BELOW and verdict != "KILL":
        return "KILL", (f"demand gate: demand_score {score}/100 ({band}) below "
                        f"{config.DEMAND_KILL_BELOW} — negligible real demand")
    if (score < config.DEMAND_CAUTION_BELOW
            and _VERDICT_RANK.get(verdict, 0) > _VERDICT_RANK["PROCEED_WITH_CAUTION"]):
        return "PROCEED_WITH_CAUTION", (
            f"demand gate: demand_score {score}/100 ({band}) below "
            f"{config.DEMAND_CAUTION_BELOW} — weak real demand, proceed with caution")
    return verdict, ""


def _strip_unsourced_competitors(competitors):
    """Drop any competitor lacking a source_url — enforces the no-invention rule."""
    out = []
    for c in competitors or []:
        if c.get("source_url"):
            out.append(c)
        else:
            log.warning("Dropping unsourced competitor: %s", c.get("name"))
    return out


def _format_prior_attempts(demand):
    """Compact, readable rendering of demand['prior_apps'] + reviews for the
    prompt (kept terse to limit token use; reviews are already snippet-capped)."""
    apps = (demand or {}).get("prior_apps") or []
    if not apps:
        return "none found — no app has shipped for this exact pain"
    lines = []
    for a in apps:
        store = "App Store" if a.get("store") == "app_store" else "Play Store"
        avg = a.get("avg")
        head = (f"- {a.get('name')} ({store}, {a.get('audience_label')}"
                f"{f', avg {avg}' if avg else ''}) "
                f"url: {a.get('url') or 'n/a'}")
        lines.append(head)
        for r in (a.get("reviews") or []):
            lines.append(f"    [{r.get('rating')}★] {r.get('text')}")
    return "\n".join(lines)


def _demand_for_prompt(demand):
    """Demand dict minus the verbose prior_apps (rendered separately as
    PRIOR_ATTEMPTS) so the DEMAND_SIGNAL block stays focused on the score."""
    if not demand:
        return "not measured"
    return {k: v for k, v in demand.items() if k != "prior_apps"}


def synthesize(research_row, validated_idea):
    """Run Pass 2 for one research row. Returns SwotAnalysis id or None on failure."""
    market_raw = research_row.market_raw or {}
    demand = market_raw.get("demand") or {}
    prompt = _PROMPT.format(
        pain=validated_idea.pain_point_title,
        demand=_demand_for_prompt(demand),
        prior=_format_prior_attempts(demand),
        strengths=research_row.strengths_raw,
        weaknesses=research_row.weaknesses_raw,
        opportunities=research_row.opportunities_raw,
        threats=research_row.threats_raw,
        market=market_raw,
    )
    try:
        result = call_json(prompt, system=_SYSTEM, max_tokens=config.CLAUDE_MAX_TOKENS)
    except ClaudeJSONError as e:
        log.warning("SWOT synthesis failed for research %d: %s", research_row.id, e)
        return None

    quadrants = {k: result.get(k, {}) for k in
                 ("strengths", "weaknesses", "opportunities", "threats")}
    competitors = _strip_unsourced_competitors(result.get("competitors"))

    base_score = _weighted_score(quadrants)
    penalty = config.RELIABILITY_PENALTY if _data_missing(research_row) else 0
    overall = max(0, base_score - penalty)
    reliability = "LOW" if penalty else "HIGH"
    verdict = _verdict(overall)

    # Demand gate: cap the verdict when measured real demand is weak/negligible.
    gated_verdict, gate_reason = _apply_demand_gate(verdict, demand)
    if gate_reason:
        log.info("Demand gate on research %d: %s -> %s (%s)",
                 research_row.id, verdict, gated_verdict, gate_reason)
        reasoning = result.get("verdict_reasoning", "")
        result["verdict_reasoning"] = (reasoning + " | " + gate_reason).strip(" |")
        verdict = gated_verdict

    session = get_session()
    try:
        analysis = SwotAnalysis(
            swot_research_id=research_row.id,
            strengths=quadrants["strengths"],
            weaknesses=quadrants["weaknesses"],
            opportunities=quadrants["opportunities"],
            threats=quadrants["threats"],
            competitors=competitors,
            market_analysis=result.get("market_analysis") or {},
            verdict=verdict,
            overall_score=overall,
            demand_score=demand.get("demand_score"),
            demand_data=demand or None,
            reliability_penalty=-penalty if penalty else 0,
            score_reliability=reliability,
            verdict_reasoning=result.get("verdict_reasoning", ""),
            biggest_risk=result.get("biggest_risk", ""),
            biggest_opportunity=result.get("biggest_opportunity", ""),
            synthesized_at=datetime.utcnow(),
        )
        session.add(analysis)
        session.commit()
        analysis_id = analysis.id
    finally:
        session.close()

    log.info("SWOT synthesis %d -> %s (%d/100, %s, demand=%s)",
             analysis_id, verdict, overall, reliability,
             demand.get("demand_score", "n/a"))
    return analysis_id


def run(research_results):
    """research_results: list of (swot_research_id, status).
    Skips 'failed' rows. Returns list of SwotAnalysis ids."""
    out = []
    for research_id, status in research_results:
        if status == "failed":
            log.info("Skipping Pass 2 for failed research %d", research_id)
            continue
        session = get_session()
        try:
            research_row = session.query(SwotResearch).get(research_id)
            if not research_row:
                continue
            validated = session.query(ValidatedIdea).get(
                research_row.validated_idea_id)
        finally:
            session.close()

        if not validated:
            continue
        aid = synthesize(research_row, validated)
        if aid:
            out.append(aid)
    return out
