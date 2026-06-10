"""Reddit scraper.

Searches configured subreddits for pain-point phrasing. Method priority:
  1. praw OAuth     — if REDDIT_CLIENT_ID/SECRET are set (dormant: Reddit closed
                      self-service API app creation, so creds are unobtainable now).
  2. Serper/Google  — `site:reddit.com/r/<sub>` via our existing SERPER key. The
                      practical primary: Reddit now 403s the no-auth .json
                      endpoints, but Google indexes Reddit deeply, so this is far
                      better targeted than RSS (full titles + pain-dense snippets).
  3. public RSS     — last-resort .rss feeds (thin: capped, HTML-truncated).

On any auth/network failure it logs and returns whatever it collected — never
raises, so the pipeline continues with other sources.
"""
import html
import logging
import re
from xml.etree import ElementTree

import requests

import config

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")
# Strip Google/Reddit title decorations. Leading: "r/SaaS on Reddit: ...".
# Trailing: "... : r/SaaS", "... — r/X - Reddit", "... - Reddit".
_TITLE_LEAD_RE = re.compile(r"^\s*r/\w+ on Reddit:\s*", re.IGNORECASE)
_TITLE_NOISE_RE = re.compile(r"\s*[-—:]\s*r/\w+(\s*[-—]\s*Reddit)?\s*$|\s*[-—]\s*Reddit\s*$",
                             re.IGNORECASE)


def _clean_title(title):
    return _TITLE_NOISE_RE.sub("", _TITLE_LEAD_RE.sub("", title or "")).strip()

log = logging.getLogger(__name__)

_reddit = None


def _client():
    global _reddit
    if _reddit is None:
        import praw
        kwargs = dict(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
        # A "script" app authenticates via the password grant: if a username +
        # password are configured, pass them. Without them praw uses
        # application-only ("userless") OAuth, which works for read-only search
        # but fails on some script-type apps.
        if config.REDDIT_USERNAME and config.REDDIT_PASSWORD:
            kwargs["username"] = config.REDDIT_USERNAME
            kwargs["password"] = config.REDDIT_PASSWORD
        _reddit = praw.Reddit(**kwargs)
        _reddit.read_only = True
    return _reddit


def _scrape_praw(subreddits, query_terms, limit):
    try:
        reddit = _client()
    except Exception as e:
        log.error("Reddit client init failed; skipping Reddit: %s", e)
        return []

    signals = []
    for sub in subreddits:
        for term in query_terms:
            try:
                results = reddit.subreddit(sub).search(
                    f'"{term}"', sort="new", limit=limit
                )
                for post in results:
                    body = getattr(post, "selftext", "") or ""
                    content = f"{post.title}\n\n{body}".strip()
                    signals.append({
                        "source": "reddit",
                        "url": f"https://reddit.com{post.permalink}",
                        "content": content,
                    })
            except Exception as e:
                # Token expiry, rate limit, subreddit errors: skip and continue.
                log.warning("Reddit search failed (r/%s, '%s'): %s", sub, term, e)
                continue
    return signals


def _scrape_search(subreddits, query_terms, results_per_sub):
    """Search Reddit via the web-search backend (Serper or Brave). Reddit closed
    its API and now 403s the .json endpoints, but Google/Brave index Reddit deeply,
    so `site:reddit.com/r/<sub>` with the pain phrases OR'd surfaces the most
    relevant complaint threads — richer and better-targeted than the .rss feed.

    Returns title + snippet (the snippet is the pain-dense excerpt). Resilient: a
    failed query is logged and skipped, never raises."""
    from utils.search import web_search

    or_terms = " OR ".join(f'"{t}"' for t in query_terms)
    signals = []
    seen = set()
    for sub in subreddits:
        q = f"site:reddit.com/r/{sub} ({or_terms})"
        try:
            hits = web_search(q, num=results_per_sub)
        except Exception as e:  # noqa: BLE001 — never break discovery
            log.warning("Reddit search failed (r/%s): %s", sub, e)
            continue
        for item in hits:
            link = item.get("link") or ""
            if "reddit.com" not in link or link in seen:
                continue
            seen.add(link)
            title = _clean_title(item.get("title"))
            snippet = (item.get("snippet") or "").strip()
            content = f"{title}\n\n{snippet}".strip()
            if content:
                signals.append({"source": "reddit", "url": link,
                                "content": content})
    return signals


def _strip_html(text):
    return html.unescape(_TAG_RE.sub(" ", text or "")).strip()


def _scrape_rss(subreddits, query_terms, limit):
    """No-auth fallback: parse Reddit's public search.rss (Atom) feeds. Needs a
    descriptive User-Agent; no API key required. Lower fidelity than OAuth (body
    is HTML), but works without credentials or approval."""
    headers = {"User-Agent": config.REDDIT_USER_AGENT}
    signals = []
    for sub in subreddits:
        for term in query_terms:
            try:
                resp = requests.get(
                    f"https://www.reddit.com/r/{sub}/search.rss",
                    params={
                        "q": f'"{term}"',
                        "restrict_sr": 1,
                        "sort": "new",
                        "limit": limit,
                    },
                    headers=headers,
                    timeout=15,
                )
                resp.raise_for_status()
                root = ElementTree.fromstring(resp.content)
                for entry in root.iter(f"{_ATOM}entry"):
                    title_el = entry.find(f"{_ATOM}title")
                    content_el = entry.find(f"{_ATOM}content")
                    link_el = entry.find(f"{_ATOM}link")
                    title = title_el.text if title_el is not None else ""
                    body = _strip_html(content_el.text) if content_el is not None else ""
                    content = f"{title}\n\n{body}".strip()
                    url = link_el.get("href") if link_el is not None else ""
                    signals.append({
                        "source": "reddit",
                        "url": url,
                        "content": content,
                    })
            except Exception as e:
                log.warning("Reddit RSS search failed (r/%s, '%s'): %s",
                            sub, term, e)
                continue
    return signals


def scrape(subreddits=None, query_terms=None, limit_per_query=None):
    """Return a list of signal dicts: {source, url, content}.

    Resilient by design: a failure on one subreddit/query is logged and skipped.
    """
    subreddits = subreddits or config.REDDIT_SUBREDDITS
    query_terms = query_terms or config.REDDIT_QUERY_TERMS
    limit = limit_per_query or config.REDDIT_POSTS_PER_QUERY

    # Method priority: PRAW OAuth (if creds) -> Serper/Google search (if key) ->
    # public RSS. Serper is the practical primary now that Reddit closed the API
    # and 403s the .json endpoints (self-service app creation also disabled).
    if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
        signals = _scrape_praw(subreddits, query_terms, limit)
    elif config.REDDIT_USE_SERPER and (config.SERPER_API_KEY or config.BRAVE_API_KEY):
        signals = _scrape_search(subreddits, query_terms,
                                 config.REDDIT_SEARCH_RESULTS)
        if not signals:  # search empty/blocked -> fall back to RSS
            log.info("Reddit web search returned nothing; falling back to RSS")
            signals = _scrape_rss(subreddits, query_terms, limit)
    else:
        log.info("Reddit credentials/search key unset; using public RSS feeds")
        signals = _scrape_rss(subreddits, query_terms, limit)

    log.info("Reddit scraped %d signals", len(signals))
    return signals
