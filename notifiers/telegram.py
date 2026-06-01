"""Telegram notifications via the Bot HTTP API (sync, no event loop needed).

Invariant: health_check() runs before any other API calls in the pipeline.
"""
import logging

import requests

import config

log = logging.getLogger(__name__)

_API = "https://api.telegram.org/bot{token}/{method}"


def _call(method, payload, timeout=15):
    if not config.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN unset")
        return None
    url = _API.format(token=config.TELEGRAM_BOT_TOKEN, method=method)
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        data = resp.json()
        if not data.get("ok"):
            log.error("Telegram %s failed: %s", method, data.get("description"))
            return None
        return data
    except requests.RequestException as e:
        log.error("Telegram %s request error: %s", method, e)
        return None


def health_check():
    """Verify the bot token is valid. Returns True on success."""
    data = _call("getMe", {})
    return bool(data and data.get("ok"))


def send_message(text, parse_mode=None):
    """Send a plain-text message to the configured chat."""
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return _call("sendMessage", payload) is not None


def _quadrant_lines(label, emoji, quadrant):
    """Render one SWOT quadrant block. `quadrant` is the synthesized dict."""
    if not quadrant:
        return [f"{emoji} {label}: n/a"]
    score = quadrant.get("score", "?")
    conf = quadrant.get("confidence", "?")
    head = f"{emoji} {label} ({score}/100 · {conf} confidence)"
    lines = [head]
    prose = (quadrant.get("prose") or "").strip()
    if prose:
        lines.append(f"   {prose}")
    return lines


def format_digest(analysis, idea=None):
    """Build the Telegram digest string for a single PROCEED(_WITH_CAUTION) idea.

    `analysis` is a dict-shaped view of a SwotAnalysis row.
    `idea` is the optional synthesized product concept dict.
    """
    title = analysis.get("pain_point_title", "Untitled")
    verdict = analysis.get("verdict", "")
    verdict_emoji = "✅" if verdict == "PROCEED" else "⚠️"
    score = analysis.get("overall_score", "?")
    reliability = analysis.get("score_reliability", "?")

    lines = [
        f"\U0001f52c SWOT COMPLETE — {title}",
        f"\U0001f4ca Score: {score}/100 · {verdict_emoji} {verdict.replace('_', ' ')}",
        f"\U0001f3af Reliability: {reliability}",
    ]
    demand = analysis.get("demand_data") or {}
    if demand and demand.get("demand_score") is not None:
        lines.append(
            f"\U0001f4c8 Demand: {demand['demand_score']}/100 "
            f"({demand.get('demand_band', '?')}) — {demand.get('summary', '')}"
        )
        prior = demand.get("prior_apps") or []
        if prior:
            tops = "; ".join(
                f"{a.get('name')} ({a.get('audience_label')})" for a in prior[:3])
            lines.append(f"\U0001f50e Prior attempts: {tops}")
    lines.append("")
    lines += _quadrant_lines("STRENGTHS", "✅", analysis.get("strengths"))
    lines.append("")
    lines += _quadrant_lines("WEAKNESSES", "⚠️", analysis.get("weaknesses"))
    lines.append("")
    lines += _quadrant_lines("OPPORTUNITIES", "\U0001f3af", analysis.get("opportunities"))
    lines.append("")
    lines += _quadrant_lines("THREATS", "\U0001f6a8", analysis.get("threats"))

    market = analysis.get("market_analysis") or {}
    if market:
        lines.append("")
        lines.append("\U0001f4c8 MARKET")
        size = market.get("market_size") or "unknown"
        tam = market.get("tam") or "unknown"
        growth = market.get("growth_trend") or "unknown"
        lines.append(f"   Size: {size} · TAM: {tam} · Growth: {growth}")
        summary = (market.get("summary") or "").strip()
        if summary:
            lines.append(f"   {summary}")

    competitors = analysis.get("competitors") or []
    if competitors:
        lines.append("")
        lines.append("\U0001f3e2 COMPETITORS")
    for c in competitors:
        bits = [c.get("name", "?")]
        if c.get("pricing"):
            bits.append(c["pricing"])
        if c.get("traction"):
            bits.append(c["traction"])
        if c.get("core_weakness"):
            bits.append(f"weak: {c['core_weakness']}")
        lines.append("   " + " · ".join(bits))

    lines.append("")
    if analysis.get("biggest_risk"):
        lines.append(f"⚡ Biggest risk: {analysis['biggest_risk']}")
    if analysis.get("biggest_opportunity"):
        lines.append(f"\U0001f3c6 Biggest opportunity: {analysis['biggest_opportunity']}")

    if idea:
        lines.append("")
        lines.append(f"\U0001f680 Product: {idea.get('name', '?')}")
        lines.append(f"\U0001f4a1 {idea.get('oneliner', '')}")
        build = idea.get("build_weeks", "?")
        revenue = idea.get("revenue_model", "?")
        lines.append(f"\U0001f527 Build: ~{build} weeks · \U0001f4b0 {revenue}")
        if idea.get("similarity_flag") and idea.get("similar_idea_id"):
            lines.append(
                f"⚠️ Similar to existing idea #{idea['similar_idea_id']} "
                "— review before building"
            )

    return "\n".join(lines)


def send_digest(analysis, idea=None):
    return send_message(format_digest(analysis, idea))
