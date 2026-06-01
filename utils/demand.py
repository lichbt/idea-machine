"""Idea-specific demand measurement.

Instead of a vague industry TAM, gauge REAL demand for a specific idea from
concrete signals a founder can act on:

  - App Store rating counts (iTunes Search API)  -> install/usage proxy
  - Play Store install counts (google-play-scraper) -> download proxy
  - Google Trends 12-month direction (pytrends)  -> search demand + momentum

These roll up into a 0-100 ``demand_score`` with a band (STRONG / MODERATE /
WEAK / VERY_WEAK) and a human-readable summary. The synthesizer uses the score
as a gate: an idea with no downloads and no search interest is not worth
following, no matter how nice the SWOT prose reads.

Every external call degrades gracefully — a store or Trends being down yields a
``status: unavailable`` sub-result and never raises, so Pass 1 always proceeds.
"""
import logging
import math
import re

import requests

import config

log = logging.getLogger(__name__)

_ITUNES_SEARCH = "https://itunes.apple.com/search"
_UA = "idea-machine/0.1"
_INSTALLS_RE = re.compile(r"[\d,]+")


# ── App Store (iTunes Search) ───────────────────────────────────────────────
def _appstore_demand(keyword, limit, country):
    """Top apps for the keyword with rating counts (a download/usage proxy)."""
    try:
        resp = requests.get(
            _ITUNES_SEARCH,
            params={"term": keyword, "entity": "software",
                    "country": country, "limit": limit},
            headers={"User-Agent": _UA},
            timeout=15,
        )
        resp.raise_for_status()
        apps = []
        for a in resp.json().get("results", []):
            if not a.get("trackId"):
                continue
            apps.append({
                "name": a.get("trackName", ""),
                "ratings": a.get("userRatingCount") or 0,
                "avg": a.get("averageUserRating"),
                "price": a.get("formattedPrice"),
                "url": a.get("trackViewUrl"),
                "track_id": a.get("trackId"),
            })
        apps.sort(key=lambda x: x["ratings"], reverse=True)
        total = sum(a["ratings"] for a in apps)
        return {
            "status": "ok",
            "apps": apps[:limit],
            "total_ratings": total,
            "top": apps[0] if apps else None,
        }
    except Exception as e:  # noqa: BLE001 - any transport/parse error is non-fatal
        log.warning("App Store demand lookup failed ('%s'): %s", keyword, e)
        return {"status": "unavailable", "apps": [], "total_ratings": 0,
                "error": str(e)}


# ── Play Store (google-play-scraper) ────────────────────────────────────────
def _parse_installs(installs):
    """'5,000,000+' -> 5000000. Returns 0 on anything unparseable."""
    if not installs:
        return 0
    m = _INSTALLS_RE.search(str(installs))
    if not m:
        return 0
    try:
        return int(m.group(0).replace(",", ""))
    except ValueError:
        return 0


def _playstore_demand(keyword, limit, country):
    """Top apps for the keyword with install counts (a hard download proxy)."""
    try:
        from google_play_scraper import search as gp_search
    except ImportError as e:
        log.info("google-play-scraper not installed (%s); skipping Play Store", e)
        return {"status": "unavailable", "apps": [], "total_installs": 0,
                "error": "package not installed"}
    try:
        hits = gp_search(keyword, n_hits=limit, lang="en", country=country)
        apps = []
        for a in hits:
            installs = _parse_installs(a.get("installs"))
            apps.append({
                "name": a.get("title", ""),
                "installs": installs,
                "installs_label": a.get("installs"),
                "avg": a.get("score"),
                "app_id": a.get("appId"),
            })
        apps.sort(key=lambda x: x["installs"], reverse=True)
        total = sum(a["installs"] for a in apps)
        return {
            "status": "ok",
            "apps": apps[:limit],
            "total_installs": total,
            "top": apps[0] if apps else None,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("Play Store demand lookup failed ('%s'): %s", keyword, e)
        return {"status": "unavailable", "apps": [], "total_installs": 0,
                "error": str(e)}


# ── Google Trends (pytrends) ────────────────────────────────────────────────
def _trend(keyword):
    """12-month search-interest direction. Returns dict or status=unavailable."""
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="en-US", tz=0)
        pytrends.build_payload([keyword], timeframe="today 12-m")
        df = pytrends.interest_over_time()
        if df.empty or keyword not in df:
            return {"status": "unavailable"}
        series = df[keyword]
        q = max(1, len(series) // 4)
        first = float(series.iloc[:q].mean())
        last = float(series.iloc[-q:].mean())
        pct = None if first == 0 else round((last - first) / first * 100, 1)
        return {
            "status": "ok",
            "keyword": keyword,
            "start_avg": round(first, 1),
            "end_avg": round(last, 1),
            "yoy_change_pct": pct,
        }
    except Exception as e:  # noqa: BLE001
        log.warning("pytrends failed for '%s': %s", keyword, e)
        return {"status": "unavailable"}


# ── Reviews (do prior attempts leave the pain unsolved?) ────────────────────
_ITUNES_REVIEWS = (
    "https://itunes.apple.com/{country}/rss/customerreviews/page=1/"
    "id={track_id}/sortby=mostrecent/json"
)


def _clip(text, n):
    text = " ".join((text or "").split())
    return text[:n]


def _appstore_reviews(track_id, country, n):
    """Recent App Store reviews, biased to low stars (unsolved-pain signal).
    Returns a list of {rating, text}; empty list on any failure."""
    if not track_id:
        return []
    try:
        url = _ITUNES_REVIEWS.format(country=country, track_id=track_id)
        resp = requests.get(url, headers={"User-Agent": _UA}, timeout=15)
        resp.raise_for_status()
        # First feed entry is the app itself (no im:rating) and is skipped below.
        entries = resp.json().get("feed", {}).get("entry", []) or []
        out = []
        for e in entries:
            rating = (e.get("im:rating") or {}).get("label")
            body = (e.get("content") or {}).get("label")
            if rating is None or not body:
                continue
            try:
                rating = int(rating)
            except (TypeError, ValueError):
                continue
            out.append({"rating": rating,
                        "text": _clip(body, config.PRIOR_ART_REVIEW_SNIPPET_CHARS)})
        out.sort(key=lambda r: r["rating"])  # complaints first
        return out[:n]
    except Exception as e:  # noqa: BLE001
        log.warning("App Store reviews failed (id=%s): %s", track_id, e)
        return []


def _playstore_reviews(app_id, country, n):
    """Most-relevant Play Store reviews, biased to low stars. Empty on failure."""
    if not app_id:
        return []
    try:
        from google_play_scraper import Sort
        from google_play_scraper import reviews as gp_reviews
    except ImportError:
        return []
    try:
        result, _ = gp_reviews(app_id, lang="en", country=country,
                               sort=Sort.MOST_RELEVANT, count=n)
        out = []
        for r in result or []:
            score = r.get("score")
            body = r.get("content")
            if score is None or not body:
                continue
            out.append({"rating": int(score),
                        "text": _clip(body, config.PRIOR_ART_REVIEW_SNIPPET_CHARS)})
        out.sort(key=lambda r: r["rating"])  # complaints first
        return out[:n]
    except Exception as e:  # noqa: BLE001
        log.warning("Play Store reviews failed (id=%s): %s", app_id, e)
        return []


# ── Scoring ─────────────────────────────────────────────────────────────────
def _volume_score(audience):
    """Log-scaled 0..VOLUME_MAX from the combined download/usage audience."""
    if audience <= 0:
        return 0
    raw = config.DEMAND_VOLUME_LOG_FACTOR * math.log10(audience)
    return int(max(0, min(config.DEMAND_VOLUME_MAX, round(raw))))


def _trend_score(trend):
    """0..TREND_MAX from Google Trends direction. Neutral midpoint when the
    signal is unavailable so flaky Trends doesn't unfairly tank the score."""
    mid = config.DEMAND_TREND_MAX // 2
    if trend.get("status") != "ok":
        return mid
    pct = trend.get("yoy_change_pct")
    if pct is None:
        return mid
    # -50% -> 0, flat -> mid, +50% -> max
    return int(max(0, min(config.DEMAND_TREND_MAX, round(mid + pct * (mid / 50.0)))))


def _band(score, measurable):
    if not measurable:
        return "UNKNOWN"
    if score >= 60:
        return "STRONG"
    if score >= 40:
        return "MODERATE"
    if score >= 20:
        return "WEAK"
    return "VERY_WEAK"


# ── Pain-specific union / dedup / rank ──────────────────────────────────────
def _norm_name(name):
    return " ".join((name or "").lower().split())


def _collect_prior_apps(queries):
    """Search each query against both stores and merge into a unified, deduped
    set of apps keyed by normalized name. The highest-audience instance of a
    name wins (and supplies the review id); matched queries accumulate.

    Returns (unified_apps, appstore_ok, playstore_ok).
    """
    unified = {}
    appstore_ok = playstore_ok = False

    def _merge(name, store, audience, audience_label, avg, url, query,
               track_id=None, app_id=None, price=None):
        key = _norm_name(name)
        if not key:
            return
        rec = unified.get(key)
        if rec is None:
            rec = {"name": name, "store": store, "audience": audience,
                   "audience_label": audience_label, "avg": avg, "price": price,
                   "url": url, "track_id": track_id, "app_id": app_id,
                   "matched_queries": [], "reviews": []}
            unified[key] = rec
        if query and query not in rec["matched_queries"]:
            rec["matched_queries"].append(query)
        if audience > rec["audience"]:  # keep the strongest instance of this name
            rec.update(store=store, audience=audience, audience_label=audience_label,
                       avg=avg, price=price, url=url, track_id=track_id, app_id=app_id)

    for q in queries:
        a = _appstore_demand(q, config.DEMAND_APPS_PER_STORE, config.DEMAND_COUNTRY)
        if a.get("status") == "ok":
            appstore_ok = True
            for app in a.get("apps", []):
                _merge(app.get("name"), "app_store", app.get("ratings", 0),
                       f"{app.get('ratings', 0):,} ratings", app.get("avg"),
                       app.get("url"), q, track_id=app.get("track_id"),
                       price=app.get("price"))
        p = _playstore_demand(q, config.DEMAND_APPS_PER_STORE, config.DEMAND_COUNTRY)
        if p.get("status") == "ok":
            playstore_ok = True
            for app in p.get("apps", []):
                _merge(app.get("name"), "play_store", app.get("installs", 0),
                       f"{app.get('installs_label') or app.get('installs', 0)} installs",
                       app.get("avg"), None, q, app_id=app.get("app_id"))

    ranked = sorted(unified.values(),
                    key=lambda r: (len(r["matched_queries"]), r["audience"]),
                    reverse=True)
    return ranked[:config.PRIOR_ART_APPS_MAX], appstore_ok, playstore_ok


def _attach_reviews(prior_apps):
    """Fetch reviews for the top few apps to reveal whether the pain persists."""
    for app in prior_apps[:config.PRIOR_ART_REVIEW_APPS]:
        n = config.PRIOR_ART_REVIEWS_PER_APP
        if app["store"] == "app_store":
            app["reviews"] = _appstore_reviews(app.get("track_id"),
                                               config.DEMAND_COUNTRY, n)
        else:
            app["reviews"] = _playstore_reviews(app.get("app_id"),
                                                config.DEMAND_COUNTRY, n)


def _summary(prior_apps, trend, score, band):
    parts = []
    if prior_apps:
        top = prior_apps[0]
        parts.append(f"{len(prior_apps)} prior app(s); top '{top['name']}' "
                     f"{top['audience_label']}")
    if trend.get("status") == "ok":
        pct = trend.get("yoy_change_pct")
        if pct is not None:
            direction = "growing" if pct > 5 else "declining" if pct < -5 else "flat"
            parts.append(f"search interest {direction} ({pct:+.0f}% YoY)")
        else:
            parts.append("search interest steady")
    else:
        parts.append("search trend unavailable")
    head = "; ".join(parts) if parts else "no prior apps or search demand found"
    return f"{head} -> demand {score}/100 ({band})."


def measure(keyword, queries=None):
    """Measure pain-specific demand. Searches the pain-specific ``queries`` (the
    Validator's app_search_queries) to find apps that already tried to fix this
    pain; demand volume is taken from those apps, not category leaders. Google
    Trends still uses the short category ``keyword`` (a head term it can resolve).
    Falls back to searching ``keyword`` when no queries are given. Always returns
    a dict.
    """
    kw = (keyword or "").strip()
    queries = [q.strip() for q in (queries or []) if q and q.strip()]
    queries = queries[:config.DEMAND_APP_QUERIES_MAX]
    search_terms = queries or ([kw] if kw else [])

    if not search_terms:
        return {"keyword": kw, "queries": [], "measurable": False,
                "demand_score": 0, "demand_band": "UNKNOWN", "prior_apps": [],
                "trend": {"status": "skipped"},
                "summary": "no keyword/queries provided; demand not measured."}

    prior_apps, appstore_ok, playstore_ok = _collect_prior_apps(search_terms)
    _attach_reviews(prior_apps)
    trend = _trend(kw) if kw else {"status": "unavailable"}

    audience = sum(a["audience"] for a in prior_apps)
    measurable = bool(prior_apps)

    score = _volume_score(audience) + _trend_score(trend)
    score = int(max(0, min(100, score)))
    band = _band(score, measurable)

    result = {
        "keyword": kw,
        "queries": queries,
        "prior_apps": prior_apps,
        "app_store": {"status": "ok" if appstore_ok else "unavailable"},
        "play_store": {"status": "ok" if playstore_ok else "unavailable"},
        "trend": trend,
        "audience": audience,
        "measurable": measurable,
        "demand_score": score,
        "demand_band": band,
        "summary": _summary(prior_apps, trend, score, band),
    }
    log.info("Demand '%s' (%d queries) -> %d/100 (%s, %d prior apps, audience=%s)",
             kw, len(search_terms), score, band, len(prior_apps), f"{audience:,}")
    return result
