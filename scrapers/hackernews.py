"""Hacker News scraper via the Algolia API (free, no auth).

Searches story + comment text for pain-point phrasing.
"""
import logging

import requests

import config

log = logging.getLogger(__name__)

_SEARCH_URL = "https://hn.algolia.com/api/v1/search"


def scrape(query_terms=None, hits_per_query=30):
    """Return a list of signal dicts: {source, url, content}."""
    query_terms = query_terms or config.REDDIT_QUERY_TERMS  # reuse pain phrases
    signals = []
    for term in query_terms:
        try:
            resp = requests.get(
                _SEARCH_URL,
                params={
                    "query": term,
                    "tags": "(story,comment)",
                    "hitsPerPage": hits_per_query,
                },
                timeout=20,
            )
            resp.raise_for_status()
            hits = resp.json().get("hits", [])
        except (requests.RequestException, ValueError) as e:
            log.warning("HN search failed ('%s'): %s", term, e)
            continue

        for hit in hits:
            content = (hit.get("title") or hit.get("comment_text")
                       or hit.get("story_text") or "").strip()
            if not content:
                continue
            object_id = hit.get("objectID")
            url = hit.get("url") or f"https://news.ycombinator.com/item?id={object_id}"
            signals.append({
                "source": "hackernews",
                "url": url,
                "content": content,
            })

    log.info("Hacker News scraped %d signals", len(signals))
    return signals
