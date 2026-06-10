"""GitHub Issues scraper (category-driven).

Surfaces DEVELOPER-TOOL pain — acute, well-articulated needs from buyers who have
budget. Mirrors the app-store approach: for each devtool CATEGORY it searches open
issues sorted by REACTIONS (how many people want it = validation, akin to app
ratings), tags each issue with its repo, and caps issues-per-repo so one mega-repo
can't dominate. Category-pain synthesis then finds requests that recur across
DIFFERENT repos = a cross-repo devtool gap.

Resilient by design: any failure (rate limit, network, malformed JSON) is logged
and skipped — never raises, so the pipeline continues with other sources.
"""
import logging
import re

import requests

import config

log = logging.getLogger(__name__)

_SEARCH_URL = "https://api.github.com/search/issues"
_UA = "idea-machine/0.1"
_REPO_RE = re.compile(r"github\.com/([^/]+/[^/]+)/issues/")


def _repo_of(url):
    m = _REPO_RE.search(url or "")
    return m.group(1) if m else None


def scrape(categories=None, per_category=None, max_per_repo=None):
    """Return signal dicts: {source, url, content, created_at, category, app}.
    `app` holds the repo (owner/name) — the cross-item axis for category-pain."""
    categories = categories or config.GITHUB_CATEGORY_TERMS
    per_category = per_category or config.GITHUB_ISSUES_PER_CATEGORY
    max_per_repo = max_per_repo or config.GITHUB_MAX_ISSUES_PER_REPO

    headers = {"Accept": "application/vnd.github+json", "User-Agent": _UA}
    if config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"

    signals = []
    for cat in categories:
        try:
            resp = requests.get(
                _SEARCH_URL,
                params={"q": f"{cat} is:issue is:open",
                        "sort": "reactions", "order": "desc",
                        "per_page": per_category},
                headers=headers,
                timeout=20,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        except (requests.RequestException, ValueError) as e:
            log.warning("GitHub search failed ('%s'): %s", cat, e)
            continue

        per_repo = {}
        for it in items:
            url = it.get("html_url")
            repo = _repo_of(url)
            if not repo or per_repo.get(repo, 0) >= max_per_repo:
                continue
            title = (it.get("title") or "").strip()
            body = (it.get("body") or "").strip()
            content = f"{title}\n\n{body}".strip()
            if not content:
                continue
            per_repo[repo] = per_repo.get(repo, 0) + 1
            signals.append({
                "source": "github",
                "url": url,
                "content": content[:2000],   # issue bodies can be huge
                "created_at": it.get("created_at"),  # ISO 8601, for recency
                "category": cat,             # for category-pain synthesis
                "app": repo,                 # cross-item axis (owner/repo)
            })

    log.info("GitHub scraped %d signals", len(signals))
    return signals
