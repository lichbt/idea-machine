"""Category-level pain synthesis for app-store + GitHub sources.

A complaint/request that recurs across MULTIPLE products in the same category is a
CATEGORY GAP — a real unmet need no incumbent solves — not one product's bug. This
groups the signals the Scout scraped by category and asks the LLM, per category,
for the 2-3 pains that span DIFFERENT products. Each becomes one high-signal
"category pain" signal (with the offending products named as evidence), REPLACING
the raw per-product signals.

Works for:
  - appstore / playstore — apps in a search category, low-star reviews.
  - github — repos in a devtool category, high-reaction feature-request issues.
The cross-item axis is the signal's `app` field (an app name, or a repo for GitHub).

Degrades gracefully: a category with too few cross-product signals, or whose LLM
call fails, passes its raw signals through unchanged — discovery never breaks.
"""
import logging

import config
from utils.claude_caller import call_json
from utils.concurrency import pmap

log = logging.getLogger(__name__)

# Sources that carry a (category, item) structure suitable for cross-product
# synthesis, with the noun used for each item in the prompt.
_UNIT = {"appstore": "app", "playstore": "app", "github": "project"}
_CATEGORY_SOURCES = tuple(_UNIT)

_SYSTEM = (
    "You analyze user complaints and feature requests to find category-level "
    "product gaps. Reply with ONLY valid JSON, no prose."
)


def _prompt(category, items, unit):
    blob = "\n".join(f"- [{name}] {text}" for name, text in items)
    return f"""Below are complaints / feature requests from MULTIPLE {unit}s in the
"{category}" category. Identify the 2-3 PAIN POINTS that recur across DIFFERENT
{unit}s — category-level gaps that NO {unit} solves well. IGNORE issues unique to a
single {unit} (one {unit}'s bug, crash, or pricing): those are not category gaps.

ITEMS:
{blob}

For each cross-{unit} pain, write a crisp one-sentence pain statement and list the
{unit}s that exhibit it. Return JSON exactly:
{{"pains": [{{"pain": "<one sentence category gap>", "apps": ["{unit}1", "{unit}2"]}}]}}"""


def _category_url(source, category):
    slug = (category or "").replace(" ", "+")
    if source == "playstore":
        return f"https://play.google.com/store/search?q={slug}&c=apps"
    if source == "github":
        return f"https://github.com/search?q={slug}+is:issue&type=issues"
    return f"https://apps.apple.com/us/search?term={slug}"


def _synthesize_one(source, category, sigs):
    """Return category-pain signal dicts for one (source, category) group, or the
    raw sigs unchanged if it can't / shouldn't be synthesized."""
    unit = _UNIT.get(source, "product")
    products = {s.get("app") for s in sigs if s.get("app")}
    if (len(sigs) < config.CATEGORY_PAIN_MIN_REVIEWS
            or len(products) < config.CATEGORY_PAIN_MIN_APPS):
        return sigs  # not enough cross-product evidence

    items = [((s.get("app") or "?"), (s.get("content") or "")[:280])
             for s in sigs[:config.CATEGORY_PAIN_MAX_REVIEWS]]
    try:
        result = call_json(_prompt(category, items, unit), system=_SYSTEM)
        pains = result.get("pains") if isinstance(result, dict) else None
    except Exception as e:  # noqa: BLE001 — discovery must never break
        log.warning("Category pain synthesis failed (%s/%s): %s; passing raw",
                    source, category, e)
        return sigs
    if not pains:
        return sigs

    url = _category_url(source, category)
    out = []
    for p in pains:
        if not isinstance(p, dict):
            continue
        pain = str(p.get("pain") or "").strip()
        if not pain:
            continue
        p_apps = ", ".join(str(a) for a in (p.get("apps") or []) if a)[:200]
        across = f" — across {unit}s: {p_apps}" if p_apps else ""
        out.append({
            "source": source,
            "url": url,
            "content": f"[{category} category{across}] {pain}",
            "category": category,
        })
    if not out:
        return sigs
    log.info("Category pains (%s/%s): %d from %d items across %d %ss",
             source, category, len(out), len(sigs), len(products), unit)
    return out


def synthesize(signals):
    """Replace per-product signals (app/play reviews, github issues) with
    cross-product category-pain signals. Other sources pass through untouched.
    Returns the full transformed signal list."""
    if not config.CATEGORY_PAIN_SYNTHESIS:
        return signals

    others = [s for s in signals if s.get("source") not in _CATEGORY_SOURCES]
    cat_sigs = [s for s in signals if s.get("source") in _CATEGORY_SOURCES]
    if not cat_sigs:
        return signals

    groups = {}
    for s in cat_sigs:
        groups.setdefault((s.get("source"), s.get("category")), []).append(s)

    # Untagged groups pass through; tagged ones are synthesized concurrently
    # (one LLM call per category, several at once).
    synthesized = [s for (src, cat), sigs in groups.items() if not cat
                   for s in sigs]
    tagged = [(src, cat, sigs) for (src, cat), sigs in groups.items() if cat]
    results = pmap(lambda t: _synthesize_one(*t), tagged)
    for (src, cat, sigs), out in zip(tagged, results):
        synthesized.extend(out if out is not None else sigs)  # raw on failure

    return others + synthesized
