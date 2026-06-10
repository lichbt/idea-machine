"""Google Play Store scraper.

Mirror of the App Store scraper, for Android. Finds apps via google-play-scraper
search, pulls their reviews, and keeps only low-star reviews (complaints), which
are concentrated pain points. No auth or API key required.

Resilient by design: a failure on one term/app is logged and skipped, and a
missing google-play-scraper package degrades to an empty result — never raises,
so the pipeline continues with other sources.
"""
import logging
import math
import re

import config

log = logging.getLogger(__name__)


def _installs_to_int(installs):
    """Parse a Play install string like '1,000,000+' into an int (0 if absent)."""
    digits = re.sub(r"[^0-9]", "", str(installs or ""))
    return int(digits) if digits else 0


def _avg_to_float(avg):
    try:
        return float(avg)
    except (TypeError, ValueError):
        return None


def _gap_score(installs, avg):
    """Rank apps by 'big market, failing incumbent': a proven install base (past
    the floor) with a low average rating (users dissatisfied) = a real gap. The
    install term is LOG-scaled so dissatisfaction dominates — otherwise a beloved
    leader with millions of installs would always outrank a failing incumbent on
    raw count, defeating the gap targeting. Apps below the audience floor get no
    boost — too small to prove a market."""
    n = _installs_to_int(installs)
    if n < config.GAP_MIN_AUDIENCE:
        return 0.0
    a = _avg_to_float(avg)
    a = a if a is not None else 5.0
    return math.log10(n) * max(0.0, 5.0 - a)


def _is_underserved(app):
    a = _avg_to_float(app.get("avg"))
    return (_installs_to_int(app.get("installs")) >= config.GAP_MIN_AUDIENCE
            and a is not None and a <= config.GAP_RATING_CEILING)


def _find_apps(term, country, limit):
    from google_play_scraper import search as gp_search

    hits = gp_search(term, n_hits=limit, lang="en", country=country)
    apps = []
    for a in hits:
        app_id = a.get("appId")
        if not app_id:
            continue
        apps.append({
            "id": app_id,
            "name": a.get("title", ""),
            "installs": a.get("installs"),
            "avg": a.get("score"),
        })
    return apps


def _market_tag(app):
    """A compact market-size line so the validator/SWOT can gauge demand: an app
    with many installs = a large, validated market."""
    parts = []
    if app.get("installs"):
        parts.append(f"{app['installs']} installs")
    if app.get("avg") is not None:
        try:
            parts.append(f"{float(app['avg']):.1f}★ avg")
        except (TypeError, ValueError):
            pass
    if _is_underserved(app):
        parts.append("UNDERSERVED")
    return ", ".join(parts)


def _app_reviews(app_id, country, n):
    from google_play_scraper import Sort
    from google_play_scraper import reviews as gp_reviews

    result, _ = gp_reviews(app_id, lang="en", country=country,
                           sort=Sort.MOST_RELEVANT, count=n)
    return result or []


def scrape(search_terms=None, apps_per_term=None, reviews_per_app=None,
           max_rating=None, country=None):
    """Return a list of signal dicts: {source, url, content}."""
    try:
        import google_play_scraper  # noqa: F401
    except ImportError as e:
        log.info("google-play-scraper not installed (%s); skipping Play Store", e)
        return []

    search_terms = search_terms or config.PLAYSTORE_SEARCH_TERMS
    apps_per_term = apps_per_term or config.PLAYSTORE_APPS_PER_TERM
    # Fetch a wider review window than we keep, since we filter to low stars.
    fetch_n = (reviews_per_app or config.PLAYSTORE_REVIEWS_PER_APP) * 5
    keep_n = reviews_per_app or config.PLAYSTORE_REVIEWS_PER_APP
    max_rating = (config.PLAYSTORE_MAX_RATING if max_rating is None else max_rating)
    country = country or config.PLAYSTORE_COUNTRY

    signals = []
    seen_apps = set()
    for term in search_terms:
        try:
            apps = _find_apps(term, country, apps_per_term)
        except Exception as e:  # noqa: BLE001
            log.warning("Play Store search failed ('%s'): %s", term, e)
            continue

        # Prioritise underserved markets (big install base, low rating).
        apps.sort(key=lambda a: _gap_score(a.get("installs"), a.get("avg")),
                  reverse=True)

        for app in apps:
            app_id, app_name = app["id"], app["name"]
            if app_id in seen_apps:
                continue
            seen_apps.add(app_id)
            try:
                reviews = _app_reviews(app_id, country, fetch_n)
            except Exception as e:  # noqa: BLE001
                log.warning("Play Store reviews failed (%s): %s", app_name, e)
                continue

            market = _market_tag(app)
            url = f"https://play.google.com/store/apps/details?id={app_id}"

            kept = 0
            for r in reviews:
                score = r.get("score")
                body = r.get("content")
                if score is None or not body:
                    continue
                try:
                    if int(score) > max_rating:
                        continue
                except (TypeError, ValueError):
                    continue
                header = f"[{app_name}" + (f" — {market}" if market else "") + "]"
                content = f"{header} {body}".strip()
                signals.append({
                    "source": "playstore",
                    "url": url,
                    "content": content,
                    "category": term,       # for category-pain synthesis
                    "app": app_name,
                })
                kept += 1
                if kept >= keep_n:
                    break

    log.info("Play Store scraped %d signals", len(signals))
    return signals
