"""Reddit scraper.

Searches configured subreddits for pain-point phrasing. Uses praw OAuth when
credentials are configured, otherwise falls back to Reddit's public RSS feeds
(no auth, no API key — Reddit closed self-service API access in late 2025, but
the .rss endpoints still serve search results). On any auth/network failure it
logs and returns whatever it has collected so far — never raises, so the
pipeline continues with other sources.
"""
import html
import logging
import re
from xml.etree import ElementTree

import requests

import config

_ATOM = "{http://www.w3.org/2005/Atom}"
_TAG_RE = re.compile(r"<[^>]+>")

log = logging.getLogger(__name__)

_reddit = None


def _client():
    global _reddit
    if _reddit is None:
        import praw
        _reddit = praw.Reddit(
            client_id=config.REDDIT_CLIENT_ID,
            client_secret=config.REDDIT_CLIENT_SECRET,
            user_agent=config.REDDIT_USER_AGENT,
        )
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

    if config.REDDIT_CLIENT_ID and config.REDDIT_CLIENT_SECRET:
        signals = _scrape_praw(subreddits, query_terms, limit)
    else:
        log.info("Reddit credentials unset; using public RSS feeds")
        signals = _scrape_rss(subreddits, query_terms, limit)

    log.info("Reddit scraped %d signals", len(signals))
    return signals
