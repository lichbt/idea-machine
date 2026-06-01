"""AppSumo scraper.

Pulls public marketplace listings (product name, pitch, tags) from AppSumo's
browse pages. AppSumo is a Next.js app that embeds page data in a
<script id="__NEXT_DATA__"> blob, so no API key or browser is needed; we parse
that JSON. Each listing is emitted as a market signal describing an existing
product so the validator can reason about adjacent gaps.

Resilient by design: a failure on one page is logged and skipped — never raises,
so the pipeline continues with other sources.
"""
import json
import logging
import re

import requests

import config

log = logging.getLogger(__name__)

_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)


def _deals_from_page(url):
    resp = requests.get(url, headers={"User-Agent": _UA}, timeout=20)
    resp.raise_for_status()
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        return []
    data = json.loads(m.group(1))
    fallback = (data.get("props", {})
                .get("pageProps", {})
                .get("fallbackData") or [])
    deals = []
    for block in fallback:
        if isinstance(block, dict):
            deals.extend(block.get("deals") or [])
    return deals


def _tag_names(deal):
    names = []
    for t in deal.get("product_tags") or []:
        if isinstance(t, dict) and t.get("name"):
            names.append(t["name"])
        elif isinstance(t, str):
            names.append(t)
    return names


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fetch_deal(product_url):
    resp = requests.get(product_url, headers={"User-Agent": _UA}, timeout=20)
    resp.raise_for_status()
    m = _NEXT_DATA_RE.search(resp.text)
    if not m:
        return {}
    data = json.loads(m.group(1))
    return (data.get("props", {}).get("pageProps", {}).get("deal")) or {}


def _market_info(product_url):
    """Fetch a listing's product page and return (market_tag, summary).

    market_tag: e.g. "895 reviews, 4.3★ avg, 85 low-star (1-2★)" — review count
    is the market-size proxy; low-star count is a dissatisfaction proxy.
    summary: AppSumo's own reviews_summary, which surfaces real complaints.
    Returns ('', '') on any failure (caller still keeps the listing).
    """
    try:
        deal = _fetch_deal(product_url)
    except Exception as e:
        log.warning("AppSumo product fetch failed (%s): %s", product_url, e)
        return "", ""

    dr = deal.get("deal_review") or {}
    count = _to_int(dr.get("review_count"))
    rating = _to_float(dr.get("average_rating"))
    low = sum(c for c in (_to_int(dr.get("review_count_1_tacos")),
                          _to_int(dr.get("review_count_2_tacos"))) if c)

    parts = []
    if count:
        parts.append(f"{count:,} reviews")
    if rating is not None:
        parts.append(f"{rating:.1f}★ avg")
    if low:
        parts.append(f"{low} low-star (1-2★)")
    summary = (deal.get("reviews_summary") or "").strip()
    return ", ".join(parts), summary


def scrape(browse_urls=None, max_listings=None, fetch_market=None):
    """Return a list of signal dicts: {source, url, content}."""
    browse_urls = browse_urls or config.APPSUMO_BROWSE_URLS
    max_listings = max_listings or config.APPSUMO_MAX_LISTINGS
    fetch_market = (config.APPSUMO_FETCH_MARKET if fetch_market is None
                    else fetch_market)

    signals = []
    seen = set()
    for url in browse_urls:
        try:
            deals = _deals_from_page(url)
        except Exception as e:
            log.warning("AppSumo browse failed (%s): %s", url, e)
            continue

        for deal in deals:
            slug = deal.get("slug") or deal.get("public_name")
            if not slug or slug in seen:
                continue
            seen.add(slug)
            name = deal.get("public_name") or slug
            desc = deal.get("card_description") or ""
            tags = ", ".join(_tag_names(deal))
            path = deal.get("get_absolute_url") or f"/products/{slug}/"
            product_url = f"https://appsumo.com{path}"

            market, summary = (_market_info(product_url) if fetch_market
                               else ("", ""))
            header = f"Existing product on AppSumo: {name}"
            if market:
                header += f" ({market})"
            content = f"{header}. {desc}".strip()
            if tags:
                content += f" Categories: {tags}."
            if summary:
                content += f" User review summary: {summary}"
            signals.append({
                "source": "appsumo",
                "url": product_url,
                "content": content,
            })
            if len(signals) >= max_listings:
                break
        if len(signals) >= max_listings:
            break

    log.info("AppSumo scraped %d signals", len(signals))
    return signals
