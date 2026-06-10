"""Pluggable web search — Serper (Google) or Brave Search API.

Every web search in the project (SWOT Pass-1 research + Reddit discovery) goes
through `web_search`, which returns a uniform list of {title, link, snippet}.
The backend is chosen by `config.SEARCH_BACKEND`:
  - 'auto'   : Serper if SERPER_API_KEY is set, else Brave (the free option).
  - 'serper' : Google via Serper (free tier caps num=10/page, so we paginate).
  - 'brave'  : Brave Search API free tier (2,000 queries/month).

Raises requests.RequestException on transport/HTTP failure — callers already
tolerate that (they log and skip the query).
"""
import logging

import requests

import config

log = logging.getLogger(__name__)

_SERPER_URL = "https://google.serper.dev/search"
_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_UA = "idea-machine/0.1"


def _serper(query, num):
    """Serper/Google. Free tier rejects num>10, so paginate to reach `num`."""
    headers = {"X-API-KEY": config.SERPER_API_KEY, "Content-Type": "application/json"}
    out = []
    page = 1
    while len(out) < num and page <= 5:
        resp = requests.post(
            _SERPER_URL, headers=headers,
            json={"q": query, "num": 10, "page": page}, timeout=20)
        resp.raise_for_status()
        organic = resp.json().get("organic", []) or []
        if not organic:
            break
        for item in organic:
            out.append({"title": item.get("title"), "link": item.get("link"),
                        "snippet": item.get("snippet")})
        page += 1
    return out[:num]


def _brave(query, num):
    """Brave Search API. count is capped at 20 per request on the free tier."""
    resp = requests.get(
        _BRAVE_URL,
        headers={"X-Subscription-Token": config.BRAVE_API_KEY,
                 "Accept": "application/json", "User-Agent": _UA},
        params={"q": query, "count": min(num, 20)}, timeout=20)
    resp.raise_for_status()
    results = ((resp.json().get("web") or {}).get("results")) or []
    return [{"title": r.get("title"), "link": r.get("url"),
             "snippet": r.get("description")} for r in results][:num]


def _backend():
    b = config.SEARCH_BACKEND
    if b in ("serper", "brave"):
        return b
    # auto: prefer Serper if its key is set, else Brave.
    if config.SERPER_API_KEY:
        return "serper"
    if config.BRAVE_API_KEY:
        return "brave"
    return "serper"  # nothing configured -> serper path will surface the misconfig


def web_search(query, num=10):
    """Return up to `num` results as [{title, link, snippet}]."""
    return _brave(query, num) if _backend() == "brave" else _serper(query, num)
