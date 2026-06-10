"""Trustpilot scraper — best-effort B2B/SaaS review complaints.

Reaches SMB/B2B pain with willingness-to-pay context (people review tools they
PAY for). Trustpilot is anti-bot protected, so this is BEST-EFFORT: it reads the
review text embedded in each page's ``__NEXT_DATA__`` JSON blob, and if the page
is blocked or the schema drifts it simply yields nothing. It is a bonus source,
never a dependency.

Resilient by design: every request and parse is guarded; failures are logged and
skipped — this module never raises, so the pipeline continues with other sources.
"""
import json
import logging
import re

import requests

import config

log = logging.getLogger(__name__)

_BASE = "https://www.trustpilot.com"
_CATEGORY_URL = _BASE + "/categories/{cat}"
_REVIEW_URL = _BASE + "/review/{domain}"
# A realistic browser UA reduces (does not eliminate) the chance of a block.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
}
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)
_BUSINESS_PER_CATEGORY = 3
_REVIEWS_PER_BUSINESS = 5


def _next_data(html):
    """Extract and parse the page's embedded __NEXT_DATA__ JSON, or None."""
    m = _NEXT_DATA_RE.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except (ValueError, TypeError):
        return None


def _walk(obj):
    """Yield every dict nested anywhere in a JSON structure."""
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


def _find_domains(data, limit):
    """Pull business domains (the /review/{domain} slug) out of category JSON."""
    domains = []
    seen = set()
    for d in _walk(data):
        dom = d.get("identifyingName") or d.get("domain")
        if isinstance(dom, str) and "." in dom and dom not in seen:
            seen.add(dom)
            domains.append(dom)
            if len(domains) >= limit:
                break
    return domains


def _find_reviews(data, max_rating, limit):
    """Pull low-star {rating, text, title} review dicts out of business JSON."""
    out = []
    for d in _walk(data):
        rating = d.get("rating") or d.get("stars")
        text = d.get("text") or d.get("reviewBody")
        if not isinstance(text, str) or not text.strip():
            continue
        try:
            r = int(rating)
        except (TypeError, ValueError):
            continue
        if r > max_rating:
            continue
        out.append({"rating": r, "title": d.get("title") or "",
                    "text": text.strip()})
        if len(out) >= limit:
            break
    return out


def _get(url):
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def scrape(categories=None, max_rating=None):
    """Return a list of signal dicts: {source, url, content}."""
    categories = categories or config.TRUSTPILOT_CATEGORIES
    max_rating = (config.TRUSTPILOT_MAX_RATING if max_rating is None
                  else max_rating)

    signals = []
    for cat in categories:
        try:
            data = _next_data(_get(_CATEGORY_URL.format(cat=cat)))
            domains = _find_domains(data, _BUSINESS_PER_CATEGORY) if data else []
        except (requests.RequestException, ValueError) as e:
            log.warning("Trustpilot category failed ('%s'): %s", cat, e)
            continue

        for domain in domains:
            try:
                bdata = _next_data(_get(_REVIEW_URL.format(domain=domain)))
                reviews = (_find_reviews(bdata, max_rating, _REVIEWS_PER_BUSINESS)
                           if bdata else [])
            except (requests.RequestException, ValueError) as e:
                log.warning("Trustpilot business failed (%s): %s", domain, e)
                continue

            for rev in reviews:
                header = f"[{domain} — {rev['rating']}★]"
                content = f"{header} {rev['title']}\n\n{rev['text']}".strip()
                signals.append({
                    "source": "trustpilot",
                    "url": _REVIEW_URL.format(domain=domain),
                    "content": content,
                })

    log.info("Trustpilot scraped %d signals", len(signals))
    return signals
