"""Render SWOT analyses (+ product concepts) to a standalone HTML file.

Self-contained: inline CSS, no external assets. Pulls rows from the DB so it
can render the latest run or any subset of analyses by id.
"""
import html
import logging
import os
from datetime import datetime

import config
from db.models import (
    Idea,
    SwotAnalysis,
    SwotResearch,
    ValidatedIdea,
    get_session,
)

log = logging.getLogger(__name__)

_QUADRANTS = [
    ("strengths", "Strengths", "s"),
    ("weaknesses", "Weaknesses", "w"),
    ("opportunities", "Opportunities", "o"),
    ("threats", "Threats", "t"),
]

_VERDICT_CLASS = {
    "PROCEED": "v-proceed",
    "PROCEED_WITH_CAUTION": "v-caution",
    "KILL": "v-kill",
}

_CSS = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  margin: 0; padding: 2rem; background: #0f1115; color: #e6e9ef; line-height: 1.5; }
.wrap { max-width: 980px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 0.25rem; }
.meta { color: #8b93a7; font-size: 0.85rem; margin-bottom: 2rem; }
.card { background: #181b22; border: 1px solid #262b36; border-radius: 12px;
  padding: 1.5rem; margin-bottom: 2rem; }
.card-head { display: flex; align-items: center; justify-content: space-between;
  gap: 1rem; flex-wrap: wrap; margin-bottom: 1rem; }
.title { font-size: 1.2rem; font-weight: 600; margin: 0; }
.badges { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
.badge { font-size: 0.75rem; font-weight: 600; padding: 0.25rem 0.6rem;
  border-radius: 999px; white-space: nowrap; }
.v-proceed { background: #14351f; color: #4ade80; border: 1px solid #1f5132; }
.v-caution { background: #3a3010; color: #fbbf24; border: 1px solid #5c4a17; }
.v-kill { background: #3a1416; color: #f87171; border: 1px solid #5c1f22; }
.score { background: #1f2430; color: #cbd5e1; border: 1px solid #303747; }
.rel-HIGH { background: #14351f; color: #4ade80; }
.rel-LOW { background: #3a3010; color: #fbbf24; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 680px) { .grid { grid-template-columns: 1fr; } }
.quad { border-radius: 10px; padding: 1rem; border: 1px solid; }
.quad.s { background: #0e2417; border-color: #1f5132; }
.quad.w { background: #2a2410; border-color: #5c4a17; }
.quad.o { background: #0e1f30; border-color: #1c456b; }
.quad.t { background: #2a1214; border-color: #5c1f22; }
.quad h3 { margin: 0 0 0.5rem; font-size: 0.95rem; display: flex;
  justify-content: space-between; align-items: baseline; gap: 0.5rem; }
.q-score { font-size: 0.8rem; color: #cbd5e1; font-weight: 600; }
.conf { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: #8b93a7; }
.bar { height: 5px; background: #00000033; border-radius: 999px; overflow: hidden;
  margin: 0.4rem 0 0.7rem; }
.bar > span { display: block; height: 100%; background: currentColor; opacity: 0.7; }
.prose { font-size: 0.88rem; color: #cdd3df; margin: 0 0 0.6rem; }
.evidence { font-size: 0.75rem; }
.evidence a { color: #7aa2f7; text-decoration: none; word-break: break-all; }
.evidence a:hover { text-decoration: underline; }
.section-h { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em;
  color: #8b93a7; margin: 1.5rem 0 0.5rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.82rem; }
th, td { text-align: left; padding: 0.5rem 0.6rem; border-bottom: 1px solid #262b36;
  vertical-align: top; }
th { color: #8b93a7; font-weight: 600; }
.risk-op { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
@media (max-width: 680px) { .risk-op { grid-template-columns: 1fr; } }
.callout { border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.85rem; }
.callout.risk { background: #2a1214; border: 1px solid #5c1f22; }
.callout.op { background: #0e2417; border: 1px solid #1f5132; }
.callout strong { display: block; margin-bottom: 0.25rem; font-size: 0.75rem;
  text-transform: uppercase; letter-spacing: 0.04em; }
.concept { background: #11161f; border: 1px dashed #2f6feb55; border-radius: 10px;
  padding: 1rem 1.2rem; margin-top: 1.5rem; }
.concept h3 { margin: 0 0 0.3rem; }
.concept .one { color: #cdd3df; margin: 0 0 0.7rem; }
.concept ul { margin: 0.3rem 0 0.7rem; padding-left: 1.2rem; }
.concept .specs { font-size: 0.82rem; color: #8b93a7; }
.sim { margin-top: 0.6rem; font-size: 0.8rem; color: #fbbf24; }
.empty { color: #8b93a7; font-style: italic; }
.market { background: #11161f; border: 1px solid #262b36; border-radius: 10px;
  padding: 1rem 1.2rem; }
.market .mstats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem;
  margin-bottom: 0.8rem; }
@media (max-width: 680px) { .market .mstats { grid-template-columns: 1fr; } }
.market .mstat { display: flex; flex-direction: column; gap: 0.25rem; }
.market .mlabel { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: #8b93a7; }
.market .mval { font-size: 0.95rem; color: #e2e8f0; font-weight: 600; }
.demand { border-radius: 10px; padding: 1rem 1.2rem; border: 1px solid #262b36;
  background: #11161f; }
.demand.dem-strong { border-color: #1f5132; background: #0e2417; }
.demand.dem-moderate { border-color: #1c456b; background: #0e1f30; }
.demand.dem-weak { border-color: #5c4a17; background: #2a2410; }
.demand.dem-unknown { border-color: #3a3f4b; background: #14181f; }
.dem-head { display: flex; align-items: baseline; gap: 0.6rem; flex-wrap: wrap;
  margin-bottom: 0.5rem; }
.dem-score { font-size: 1.4rem; font-weight: 700; color: #e2e8f0; }
.dem-band { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em;
  font-weight: 600; color: #cbd5e1; }
.dem-kw { font-size: 0.78rem; color: #8b93a7; }
.badge.demand-badge { background: #11233a; color: #7aa2f7; }
.dem-stores { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem;
  margin-top: 0.6rem; }
@media (max-width: 680px) { .dem-stores { grid-template-columns: 1fr; } }
.dem-store-h { font-size: 0.7rem; text-transform: uppercase; letter-spacing: 0.04em;
  color: #8b93a7; margin-bottom: 0.3rem; }
.dem-table { font-size: 0.8rem; }
.dem-table td { padding: 0.3rem 0.5rem; border-bottom: 1px solid #20252f; }
.dem-table td.num { text-align: right; color: #cbd5e1; white-space: nowrap; }
.dem-app { margin-top: 0.5rem; padding: 0.5rem 0.7rem; border: 1px solid #20252f;
  border-radius: 6px; background: #0c1016; }
.dem-app-h { display: flex; align-items: baseline; gap: 0.5rem; flex-wrap: wrap; }
.dem-app-name { font-weight: 600; color: #e2e8f0; font-size: 0.86rem; }
.dem-app-name a { color: #7aa2f7; text-decoration: none; }
.dem-app-meta { font-size: 0.75rem; color: #9aa3b4; white-space: nowrap; }
.dem-q { font-size: 0.72rem; color: #6b7488; }
.dem-reviews { list-style: none; margin: 0.4rem 0 0; padding: 0; }
.dem-review { font-size: 0.78rem; color: #b8c0cf; padding: 0.2rem 0;
  border-top: 1px solid #181d25; }
.dem-stars { color: #d9a441; margin-right: 0.3rem; white-space: nowrap; }
"""


def _esc(value):
    return html.escape(str(value)) if value is not None else ""


def _quad_html(key, label, css, quad):
    if not quad:
        return f'<div class="quad {css}"><h3>{label}</h3>' \
               f'<p class="prose empty">No data.</p></div>'
    score = quad.get("score", 0)
    try:
        pct = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        pct = 0
    conf = _esc(quad.get("confidence", "?"))
    prose = _esc(quad.get("prose", ""))
    evidence = quad.get("evidence") or []
    ev_html = ""
    if evidence:
        links = "".join(
            f'<div><a href="{_esc(u)}" target="_blank" rel="noopener">{_esc(u)}</a></div>'
            for u in evidence if u
        )
        ev_html = f'<div class="evidence">{links}</div>'
    return f"""<div class="quad {css}">
      <h3>{label} <span class="q-score">{_esc(score)}/100 · <span class="conf">{conf}</span></span></h3>
      <div class="bar"><span style="width:{pct}%"></span></div>
      <p class="prose">{prose}</p>
      {ev_html}
    </div>"""


def _competitors_html(competitors):
    if not competitors:
        return '<p class="prose empty">No sourced competitors found.</p>'
    rows = ""
    for c in competitors:
        name = _esc(c.get("name"))
        src = c.get("source_url")
        if src:
            name = f'<a href="{_esc(src)}" target="_blank" rel="noopener">{name}</a>'
        big = "Yes" if c.get("big_player_risk") else "No"
        rows += f"""<tr>
          <td>{name}</td>
          <td>{_esc(c.get("pricing"))}</td>
          <td>{_esc(c.get("traction"))}</td>
          <td>{_esc(c.get("core_weakness"))}</td>
          <td>{big}</td>
        </tr>"""
    return f"""<table>
      <thead><tr><th>Competitor</th><th>Pricing</th><th>Traction</th>
        <th>Core weakness</th><th>Big-player risk</th></tr></thead>
      <tbody>{rows}</tbody></table>"""


_DEMAND_BAND_CLASS = {
    "STRONG": "dem-strong", "MODERATE": "dem-moderate",
    "WEAK": "dem-weak", "VERY_WEAK": "dem-weak", "UNKNOWN": "dem-unknown",
}


def _demand_html(demand):
    """Render the measured demand panel: download/install counts + search trend."""
    if not demand:
        return '<p class="prose empty">Demand not measured.</p>'
    score = demand.get("demand_score", "?")
    band = demand.get("demand_band", "UNKNOWN")
    bclass = _DEMAND_BAND_CLASS.get(band, "dem-unknown")
    keyword = _esc(demand.get("keyword"))

    def _app_block(a):
        store = "App Store" if a.get("store") == "app_store" else "Play Store"
        avg = a.get("avg")
        avg_disp = f" · {avg:.1f}★" if isinstance(avg, (int, float)) else ""
        url = a.get("url")
        name = _esc(a.get("name"))
        name_html = f'<a href="{_esc(url)}" target="_blank">{name}</a>' if url else name
        matched = a.get("matched_queries") or []
        matched_disp = (f' <span class="dem-q">↳ {_esc(", ".join(matched))}</span>'
                        if matched else "")
        reviews = a.get("reviews") or []
        rev_html = ""
        if reviews:
            items = "".join(
                f'<li class="dem-review"><span class="dem-stars">'
                f'{"★" * int(r.get("rating") or 0)}</span> {_esc(r.get("text"))}</li>'
                for r in reviews[:5])
            rev_html = f'<ul class="dem-reviews">{items}</ul>'
        return (f'<div class="dem-app"><div class="dem-app-h">'
                f'<span class="dem-app-name">{name_html}</span>'
                f'<span class="dem-app-meta">{store} · {_esc(a.get("audience_label"))}'
                f'{avg_disp}</span>{matched_disp}</div>{rev_html}</div>')

    prior = demand.get("prior_apps") or []
    trend = demand.get("trend") or {}
    if trend.get("status") == "ok":
        pct = trend.get("yoy_change_pct")
        trend_disp = (f"{pct:+.0f}% YoY" if pct is not None else "steady")
    else:
        trend_disp = "unavailable"

    if prior:
        apps_html = ('<div class="dem-store-h">Prior attempts '
                     '(apps that tried this pain) · reviews biased to complaints</div>'
                     + "".join(_app_block(a) for a in prior))
    else:
        apps_html = ('<p class="prose empty">No app has shipped for this exact '
                     'pain (possible blue ocean — or no demand).</p>')
    return f"""<div class="demand {bclass}">
      <div class="dem-head">
        <span class="dem-score">{_esc(score)}/100</span>
        <span class="dem-band">{_esc(band.replace("_", " "))}</span>
        <span class="dem-kw">“{keyword}” · search trend {_esc(trend_disp)}</span>
      </div>
      <p class="prose">{_esc(demand.get("summary"))}</p>
      {apps_html}
    </div>"""


def _market_html(market):
    if not market:
        return '<p class="prose empty">No market analysis.</p>'
    cells = [
        ("Market size", market.get("market_size")),
        ("TAM", market.get("tam")),
        ("Growth", market.get("growth_trend")),
    ]
    stat_html = "".join(
        f'<div class="mstat"><span class="mlabel">{_esc(lbl)}</span>'
        f'<span class="mval">{_esc(val or "unknown")}</span></div>'
        for lbl, val in cells
    )
    summary = _esc(market.get("summary"))
    evidence = market.get("evidence") or []
    ev_html = ""
    if evidence:
        links = "".join(
            f'<div><a href="{_esc(u)}" target="_blank" rel="noopener">{_esc(u)}</a></div>'
            for u in evidence if u
        )
        ev_html = f'<div class="evidence">{links}</div>'
    summary_html = f'<p class="prose">{summary}</p>' if summary else ""
    return f'<div class="market"><div class="mstats">{stat_html}</div>' \
           f'{summary_html}{ev_html}</div>'


def _concept_html(idea):
    if not idea:
        return ""
    features = idea.get("core_features") or []
    feat_html = "".join(f"<li>{_esc(f)}</li>" for f in features)
    sim = ""
    if idea.get("similarity_flag") and idea.get("similar_idea_id"):
        sim = (f'<div class="sim">⚠ Similar to existing idea '
               f'#{_esc(idea["similar_idea_id"])} — review before building</div>')
    return f"""<div class="concept">
      <h3>🚀 {_esc(idea.get("name"))}</h3>
      <p class="one">{_esc(idea.get("oneliner"))}</p>
      <ul>{feat_html}</ul>
      <div class="specs">🔧 Stack: {_esc(idea.get("tech_stack"))}
        &nbsp;·&nbsp; ⏱ Build: ~{_esc(idea.get("build_weeks"))} weeks
        &nbsp;·&nbsp; 💰 {_esc(idea.get("revenue_model"))}</div>
      {sim}
    </div>"""


def _card_html(view):
    verdict = view.get("verdict", "")
    vclass = _VERDICT_CLASS.get(verdict, "score")
    rel = view.get("score_reliability", "")
    quads = "".join(
        _quad_html(key, label, css, view.get(key))
        for key, label, css in _QUADRANTS
    )
    risk = _esc(view.get("biggest_risk"))
    op = _esc(view.get("biggest_opportunity"))
    demand = view.get("demand_data")
    demand_badge = ""
    if demand and demand.get("demand_score") is not None:
        demand_badge = (f'<span class="badge demand-badge">Demand '
                        f'{_esc(demand.get("demand_score"))}/100 · '
                        f'{_esc((demand.get("demand_band") or "").replace("_", " "))}</span>')
    return f"""<div class="card">
      <div class="card-head">
        <h2 class="title">{_esc(view.get("pain_point_title", "Untitled"))}</h2>
        <div class="badges">
          <span class="badge score">{_esc(view.get("overall_score", "?"))}/100</span>
          <span class="badge {vclass}">{_esc(verdict.replace("_", " "))}</span>
          {demand_badge}
          <span class="badge rel-{_esc(rel)}">Reliability: {_esc(rel)}</span>
        </div>
      </div>
      <div class="section-h">Demand (downloads + search trend)</div>
      {_demand_html(view.get("demand_data"))}
      <div class="grid">{quads}</div>
      <div class="section-h">Market analysis</div>
      {_market_html(view.get("market_analysis"))}
      <div class="section-h">Competitors</div>
      {_competitors_html(view.get("competitors"))}
      <div class="risk-op" style="margin-top:1.2rem">
        <div class="callout risk"><strong>⚡ Biggest risk</strong>{risk}</div>
        <div class="callout op"><strong>🏆 Biggest opportunity</strong>{op}</div>
      </div>
      {_concept_html(view.get("idea"))}
    </div>"""


def build_html(views):
    """Render a list of analysis view dicts to a full HTML document string."""
    cards = "".join(_card_html(v) for v in views) or \
        '<p class="empty">No SWOT analyses found.</p>'
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SWOT Report</title>
<style>{_CSS}</style>
</head><body><div class="wrap">
  <h1>🔬 SWOT Analysis Report</h1>
  <div class="meta">Generated {now} · {len(views)} analysis(es)</div>
  {cards}
</div></body></html>"""


def _view_for(session, analysis):
    research = session.query(SwotResearch).get(analysis.swot_research_id)
    validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                 if research else None)
    idea_row = (session.query(Idea)
                .filter_by(swot_analysis_id=analysis.id)
                .order_by(Idea.id.desc()).first())
    idea = None
    if idea_row:
        idea = {
            "name": idea_row.name,
            "oneliner": idea_row.oneliner,
            "core_features": idea_row.core_features,
            "tech_stack": idea_row.tech_stack,
            "revenue_model": idea_row.revenue_model,
            "build_weeks": idea_row.build_weeks,
            "similarity_flag": idea_row.similarity_flag,
            "similar_idea_id": idea_row.similar_idea_id,
        }
    return {
        "pain_point_title": validated.pain_point_title if validated else "Untitled",
        "verdict": analysis.verdict,
        "overall_score": analysis.overall_score,
        "demand_score": analysis.demand_score,
        "demand_data": analysis.demand_data,
        "score_reliability": analysis.score_reliability,
        "strengths": analysis.strengths,
        "weaknesses": analysis.weaknesses,
        "opportunities": analysis.opportunities,
        "threats": analysis.threats,
        "competitors": analysis.competitors,
        "market_analysis": analysis.market_analysis,
        "biggest_risk": analysis.biggest_risk,
        "biggest_opportunity": analysis.biggest_opportunity,
        "idea": idea,
    }


def generate(path=None, analysis_ids=None):
    """Render SWOT analyses from the DB to an HTML file. Returns the file path.

    analysis_ids: render only these (in given order); default = all, newest first.
    """
    session = get_session()
    try:
        if analysis_ids:
            order = {aid: i for i, aid in enumerate(analysis_ids)}
            rows = (session.query(SwotAnalysis)
                    .filter(SwotAnalysis.id.in_(analysis_ids)).all())
            rows.sort(key=lambda a: order.get(a.id, 0))
        else:
            rows = session.query(SwotAnalysis).order_by(SwotAnalysis.id.desc()).all()
        views = [_view_for(session, a) for a in rows]
    finally:
        session.close()

    html_doc = build_html(views)

    if path is None:
        reports_dir = os.path.join(config.BASE_DIR, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(reports_dir, f"swot_report_{ts}.html")
    else:
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(html_doc)
    log.info("Wrote HTML report (%d analyses) -> %s", len(views), path)
    return path
