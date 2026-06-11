"""Ecosystem-wave scraper ("picks & shovels") — demand-first discovery.

Unlike the complaint-mining scrapers, this one doesn't look for pain that users
already report; it looks for WAVES — fast-growing platforms (protocols, SDKs,
frameworks, runtimes) that other developers build on — and asks: which standard
tooling categories around this wave are still unserved? A young ecosystem's
growth IS the demand signal, and competition hasn't arrived yet. MCPScope (the
machine's only PROCEED out of 86 analyses) was exactly this archetype, found by
accident via one HN post; this scraper generates the archetype on purpose.

Three phases:
  1. Wave detection (GitHub search API, free): repos created in the last
     ECOSYSTEM_MAX_AGE_DAYS with >= ECOSYSTEM_MIN_STARS, ranked by star
     VELOCITY (stars/day of age).
  2. Platform filter (one LLM call): keep only platform-shaped repos — things
     developers build ON — dropping apps, model weights, lists, and courses.
     Degrades to a keyword heuristic if the LLM is unavailable.
  3. Gap probe (GitHub API) + synthesis (one LLM call): for each top wave,
     search for existing tooling per ECOSYSTEM_GAP_TERMS category; sparse or
     low-star results = an unserved gap. The LLM turns wave + unserved gaps +
     evidence into pain-style signals the validator scores like any other.

Resilient by design: every phase logs and degrades — never raises. Works
unauthenticated (~10 req/min, throttled); set GITHUB_TOKEN for 30 req/min.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import requests

import config
from utils.claude_caller import call_json

log = logging.getLogger(__name__)

_REPO_SEARCH_URL = "https://api.github.com/search/repositories"
_UA = "idea-machine/0.1"

# Words that mark a repo as platform-shaped (phase-2 fallback heuristic only).
_PLATFORM_WORDS = (
    "protocol", "sdk", "framework", "runtime", "specification", "spec",
    "toolkit", "engine", "compiler", "language", "api", "standard", "platform",
)


def _headers():
    h = {"Accept": "application/vnd.github+json", "User-Agent": _UA}
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return h


def _throttle():
    """GitHub search rate limit: 10 req/min unauthenticated, 30 with a token."""
    time.sleep(0.5 if config.GITHUB_TOKEN else 6.5)


def _age_days(created_at, now=None):
    """Days since an ISO-8601 timestamp; None on garbage."""
    try:
        dt = datetime.strptime(str(created_at), "%Y-%m-%dT%H:%M:%SZ")
        dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None
    now = now or datetime.now(timezone.utc)
    return max((now - dt).days, 1)


def _detect_waves(max_age_days=None, min_stars=None, limit=None):
    """Velocity-ranked young, popular repos. Returns [] on any failure."""
    max_age_days = max_age_days or config.ECOSYSTEM_MAX_AGE_DAYS
    min_stars = min_stars or config.ECOSYSTEM_MIN_STARS
    limit = limit or config.ECOSYSTEM_CANDIDATES

    cutoff = (datetime.now(timezone.utc)
              - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    try:
        resp = requests.get(
            _REPO_SEARCH_URL,
            params={"q": f"created:>{cutoff} stars:>={min_stars} archived:false",
                    "sort": "stars", "order": "desc", "per_page": min(limit * 2, 100)},
            headers=_headers(), timeout=20,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except (requests.RequestException, ValueError) as e:
        log.warning("Ecosystem wave detection failed: %s", e)
        return []

    waves = []
    for it in items:
        age = _age_days(it.get("created_at"))
        stars = it.get("stargazers_count") or 0
        if not age:
            continue
        waves.append({
            "full_name": it.get("full_name"),
            "url": it.get("html_url"),
            "description": (it.get("description") or "")[:300],
            "topics": (it.get("topics") or [])[:8],
            "language": it.get("language"),
            "stars": stars,
            "age_days": age,
            "velocity": round(stars / age, 1),   # stars per day
        })
    waves.sort(key=lambda w: w["velocity"], reverse=True)
    return waves[:limit]


_FILTER_SYSTEM = (
    "You identify PLATFORM-shaped repositories: protocols, SDKs, frameworks, "
    "runtimes, specs — things OTHER developers build on, which therefore need "
    "an ecosystem of tooling around them. You exclude end-user apps, model "
    "weights, awesome-lists, courses, and one-off demos.")


def _select_platforms(candidates, top=None):
    """One LLM call: keep platform-shaped waves, best opportunity first.
    Falls back to a keyword heuristic if the LLM is unavailable."""
    top = top or config.ECOSYSTEM_TOP_WAVES
    lines = "\n".join(
        f"- {w['full_name']} | ★{w['stars']} | {w['velocity']}/day | "
        f"{w['age_days']}d old | topics: {', '.join(w['topics'])} | "
        f"{w['description']}"
        for w in candidates)
    prompt = f"""Fast-growing GitHub repos (last ~18 months), ranked by star velocity:

{lines}

Pick the {top} best PLATFORM-shaped waves — repos other developers build ON, where
a solo founder could ship paid or open-source TOOLING around the ecosystem.
Exclude apps, model checkpoints, lists, tutorials.

Return JSON: {{"waves": ["owner/name", ...]}} (best opportunity first, max {top})."""
    try:
        result = call_json(prompt, system=_FILTER_SYSTEM)
        names = result.get("waves") if isinstance(result, dict) else None
        if names:
            by_name = {w["full_name"]: w for w in candidates}
            picked = [by_name[n] for n in names if n in by_name]
            if picked:
                return picked[:top]
    except Exception as e:  # noqa: BLE001 — discovery must never break
        log.warning("Wave platform filter failed (%s); using heuristic", e)

    def looks_platform(w):
        text = " ".join([w["description"].lower()] + [t.lower() for t in w["topics"]])
        return any(word in text for word in _PLATFORM_WORDS)
    return [w for w in candidates if looks_platform(w)][:top]


def _short_name(full_name):
    """The searchable ecosystem name: the repo half ('vercel/ai' -> 'ai'),
    or the owner when the repo half is a generic artifact name
    ('modelcontextprotocol/python-sdk' -> 'modelcontextprotocol')."""
    owner, _, repo = (full_name or "").partition("/")
    generic = any(g in repo.lower() for g in ("sdk", "core", "spec", "docs",
                                              "example", "samples"))
    return owner if generic else repo


def classify_gap(total_count, top_stars, saturated_stars=None):
    """A gap is unserved when nothing substantial exists for it yet."""
    saturated_stars = saturated_stars or config.ECOSYSTEM_GAP_SATURATED_STARS
    return total_count < 5 or top_stars < saturated_stars


def _probe_gaps(wave, gap_terms=None):
    """For each tooling category, how served is it already? Returns
    {term: {count, top_stars, top_repo, unserved}}; probe failures are skipped
    (absence of evidence is NOT treated as an unserved gap)."""
    gap_terms = gap_terms or config.ECOSYSTEM_GAP_TERMS
    name = _short_name(wave["full_name"])
    probes = {}
    for term in gap_terms:
        _throttle()
        try:
            resp = requests.get(
                _REPO_SEARCH_URL,
                params={"q": f'"{name}" {term} in:name,description',
                        "sort": "stars", "order": "desc", "per_page": 1},
                headers=_headers(), timeout=20,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            log.warning("Gap probe failed (%s / %s): %s", name, term, e)
            continue
        items = data.get("items", [])
        top_stars = (items[0].get("stargazers_count") or 0) if items else 0
        probes[term] = {
            "count": data.get("total_count", 0),
            "top_stars": top_stars,
            "top_repo": items[0].get("full_name") if items else None,
            "unserved": classify_gap(data.get("total_count", 0), top_stars),
        }
    return probes


_SYNTH_SYSTEM = (
    "You turn ecosystem tooling gaps into developer pain statements. Write like "
    "a developer venting a concrete workflow problem: who hurts, what they "
    "cannot do today, what they resort to instead, and why it is getting worse "
    "as the ecosystem grows. Specific and falsifiable, no marketing language.")


def _synthesize_signals(waves, per_wave=None):
    """One batched LLM call: (wave + unserved gaps + evidence) -> pain-style
    signal dicts shaped exactly like every other scraper's output."""
    per_wave = per_wave or config.ECOSYSTEM_SIGNALS_PER_WAVE
    blocks = []
    for w in waves:
        unserved = {t: p for t, p in (w.get("gaps") or {}).items() if p["unserved"]}
        if not unserved:
            continue
        gap_lines = "\n".join(
            f"  - {t}: {p['count']} repos exist, strongest ★{p['top_stars']}"
            f"{' (' + p['top_repo'] + ')' if p['top_repo'] else ''}"
            for t, p in unserved.items())
        blocks.append(
            f"ECOSYSTEM: {w['full_name']} (★{w['stars']}, {w['velocity']} stars/day,"
            f" {w['age_days']} days old)\n{w['description']}\n"
            f"UNSERVED TOOLING GAPS (little/nothing exists yet):\n{gap_lines}")
    if not blocks:
        return []

    prompt = f"""Fast-growing developer ecosystems and their unserved tooling gaps:

{chr(10).join(blocks)}

For each ecosystem, write up to {per_wave} pain statements (3-5 sentences each) for
the MOST promising gaps — the pain a developer in that ecosystem hits because the
tooling doesn't exist. Name the ecosystem explicitly and cite the growth evidence.

Return JSON: {{"signals": [{{"ecosystem": "owner/name", "gap": "<term>",
"pain": "<statement>"}}, ...]}}"""
    try:
        result = call_json(prompt, system=_SYNTH_SYSTEM)
        raw = result.get("signals") if isinstance(result, dict) else None
    except Exception as e:  # noqa: BLE001
        log.warning("Ecosystem gap synthesis failed: %s", e)
        return []
    if not raw:
        return []

    by_name = {w["full_name"]: w for w in waves}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    signals = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        pain = str(s.get("pain") or "").strip()
        wave = by_name.get(s.get("ecosystem"))
        if not pain or wave is None:
            continue
        eco = wave["full_name"]
        signals.append({
            "source": "ecosystem",
            "url": wave["url"],
            "content": f"[{eco} ecosystem — {s.get('gap')}] {pain}"[:2000],
            "created_at": now_iso,        # the wave is current by construction
            "category": eco,
            "app": eco,
            "synthesized": True,          # deliberate signal: skip cluster gate
        })
    return signals


def scrape(top_waves=None, signals_per_wave=None):
    """Return ecosystem-gap signal dicts: {source, url, content, created_at,
    category, app, synthesized}. Never raises."""
    try:
        candidates = _detect_waves()
        if not candidates:
            log.info("Ecosystem scout: no wave candidates")
            return []
        waves = _select_platforms(candidates, top=top_waves)
        if not waves:
            log.info("Ecosystem scout: no platform-shaped waves")
            return []
        for w in waves:
            w["gaps"] = _probe_gaps(w)
        signals = _synthesize_signals(waves, per_wave=signals_per_wave)
        log.info("Ecosystem scout: %d waves -> %d gap signals",
                 len(waves), len(signals))
        return signals
    except Exception as e:  # noqa: BLE001 — belt-and-suspenders
        log.error("Ecosystem scout raised, returning nothing: %s", e)
        return []
