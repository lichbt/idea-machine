"""App Store scraper.

Finds apps via the public iTunes Search API, then pulls their customer reviews
from the public RSS feed and keeps only low-star reviews (complaints), which are
concentrated pain points. No auth or API key required.

Resilient by design: a failure on one term/app is logged and skipped — never
raises, so the pipeline continues with other sources.
"""
import logging
import math

import requests

import config

log = logging.getLogger(__name__)

_SEARCH_URL = "https://itunes.apple.com/search"
_REVIEWS_URL = (
    "https://itunes.apple.com/rss/customerreviews/page=1/id={app_id}"
    "/sortby=mostrecent/json?cc={country}"
)
_UA = "idea-machine/0.1"


def _find_apps(term, country, limit):
    resp = requests.get(
        _SEARCH_URL,
        params={"term": term, "entity": "software",
                "country": country, "limit": limit},
        headers={"User-Agent": _UA},
        timeout=20,
    )
    resp.raise_for_status()
    apps = []
    for a in resp.json().get("results", []):
        if not a.get("trackId"):
            continue
        apps.append({
            "id": a["trackId"],
            "name": a.get("trackName", ""),
            "ratings": a.get("userRatingCount"),
            "avg": a.get("averageUserRating"),
            "price": a.get("formattedPrice"),
        })
    return apps


def _gap_score(ratings, avg):
    """Rank apps by 'big market, failing incumbent'. A proven audience (rating
    COUNT past the floor) combined with a LOW average rating (users dissatisfied)
    = a real gap. The audience term is LOG-scaled so dissatisfaction dominates:
    otherwise a beloved 4.7★ leader with millions of ratings would always outrank
    a failing 3.0★ incumbent purely on raw count, defeating the gap targeting.
    Apps below the audience floor get no boost — too small to prove a market."""
    if not ratings or ratings < config.GAP_MIN_AUDIENCE:
        return 0.0
    a = avg if isinstance(avg, (int, float)) else 5.0
    return math.log10(ratings) * max(0.0, 5.0 - a)


def _is_underserved(app):
    return (app.get("ratings") and app["ratings"] >= config.GAP_MIN_AUDIENCE
            and isinstance(app.get("avg"), (int, float))
            and app["avg"] <= config.GAP_RATING_CEILING)


def _market_tag(app):
    """A compact market-size line so the validator/SWOT can gauge demand: an app
    with many ratings = a large, validated market. Flags UNDERSERVED when a big
    audience is paired with a low rating (a gap worth attacking)."""
    parts = []
    if app.get("ratings") is not None:
        parts.append(f"{app['ratings']:,} ratings")
    if app.get("avg") is not None:
        parts.append(f"{app['avg']:.1f}★ avg")
    if app.get("price"):
        parts.append(app["price"])
    if _is_underserved(app):
        parts.append("UNDERSERVED")
    return ", ".join(parts)


def _app_reviews(app_id, country):
    resp = requests.get(
        _REVIEWS_URL.format(app_id=app_id, country=country),
        headers={"User-Agent": _UA},
        timeout=20,
    )
    resp.raise_for_status()
    # entries may be absent; Apple also returns a single dict (not a list) when an
    # app has exactly one review — normalise that to a list so callers can iterate.
    entries = resp.json().get("feed", {}).get("entry", []) or []
    if isinstance(entries, dict):
        entries = [entries]
    return entries


def scrape(search_terms=None, apps_per_term=None, reviews_per_app=None,
           max_rating=None, country=None):
    """Return a list of signal dicts: {source, url, content}."""
    search_terms = search_terms or config.APPSTORE_SEARCH_TERMS
    apps_per_term = apps_per_term or config.APPSTORE_APPS_PER_TERM
    reviews_per_app = reviews_per_app or config.APPSTORE_REVIEWS_PER_APP
    max_rating = config.APPSTORE_MAX_RATING if max_rating is None else max_rating
    country = country or config.APPSTORE_COUNTRY

    signals = []
    seen_apps = set()
    for term in search_terms:
        try:
            apps = _find_apps(term, country, apps_per_term)
        except Exception as e:
            log.warning("App Store search failed ('%s'): %s", term, e)
            continue

        # Prioritise underserved markets (big audience, low rating) over leaders.
        apps.sort(key=lambda a: _gap_score(a.get("ratings"), a.get("avg")),
                  reverse=True)

        for app in apps:
            app_id, app_name = app["id"], app["name"]
            if app_id in seen_apps:
                continue
            seen_apps.add(app_id)
            try:
                entries = _app_reviews(app_id, country)
            except Exception as e:
                log.warning("App Store reviews failed (%s): %s", app_name, e)
                continue

            market = _market_tag(app)

            kept = 0
            for entry in entries:
                rating = entry.get("im:rating", {}).get("label")
                if not rating:
                    continue  # feed metadata / no rating
                try:
                    if int(rating) > max_rating:
                        continue
                except ValueError:
                    continue
                title = entry.get("title", {}).get("label", "") or ""
                body = entry.get("content", {}).get("label", "") or ""
                header = f"[{app_name}" + (f" — {market}" if market else "") + "]"
                content = f"{header} {title}\n\n{body}".strip()
                url = (entry.get("link", {}).get("attributes", {}).get("href")
                       or f"https://apps.apple.com/app/id{app_id}")
                signals.append({
                    "source": "appstore",
                    "url": url,
                    "content": content,
                    "category": term,       # for category-pain synthesis
                    "app": app_name,
                })
                kept += 1
                if kept >= reviews_per_app:
                    break

    log.info("App Store scraped %d signals", len(signals))
    return signals
