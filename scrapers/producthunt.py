"""Product Hunt scraper.

Queries the official Product Hunt GraphQL API (v2) for recent launches and their
comments, surfacing comment bodies + taglines as pain-point signals (comments on
fresh launches are rich with "I wish it did X" / "why no Y" feedback).

Requires a developer token (PRODUCTHUNT_API_TOKEN, from
https://www.producthunt.com/v2/oauth/applications). When the token is unset the
scraper logs and returns no signals, so the pipeline runs on the other sources.

Resilient by design: any auth/network/parse failure is logged and yields an
empty result — never raises.
"""
import logging

import requests

import config

log = logging.getLogger(__name__)

_API = "https://api.producthunt.com/v2/api/graphql"

_QUERY = """
query($first: Int!, $comments: Int!) {
  posts(order: NEWEST, first: $first) {
    edges {
      node {
        name
        tagline
        url
        comments(first: $comments) {
          edges { node { body } }
        }
      }
    }
  }
}
"""


def scrape(posts=None, comments_per_post=None):
    """Return a list of signal dicts: {source, url, content}."""
    token = config.PRODUCTHUNT_API_TOKEN
    if not token:
        log.info("PRODUCTHUNT_API_TOKEN unset; skipping Product Hunt")
        return []

    posts = posts or config.PRODUCTHUNT_POSTS
    comments_per_post = comments_per_post or config.PRODUCTHUNT_COMMENTS_PER_POST

    try:
        resp = requests.post(
            _API,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"query": _QUERY,
                  "variables": {"first": posts, "comments": comments_per_post}},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        log.warning("Product Hunt API request failed: %s", e)
        return []

    if data.get("errors"):
        log.warning("Product Hunt API returned errors: %s", data["errors"])
        return []

    signals = []
    edges = (((data.get("data") or {}).get("posts") or {}).get("edges")) or []
    for edge in edges:
        node = (edge or {}).get("node") or {}
        name = node.get("name", "")
        tagline = node.get("tagline", "")
        url = node.get("url", "")
        comment_edges = ((node.get("comments") or {}).get("edges")) or []
        for c in comment_edges:
            body = ((c or {}).get("node") or {}).get("body") or ""
            body = body.strip()
            if not body:
                continue
            header = f"[{name}" + (f" — {tagline}" if tagline else "") + "]"
            signals.append({
                "source": "producthunt",
                "url": url,
                "content": f"{header} {body}".strip(),
            })

    log.info("Product Hunt scraped %d signals", len(signals))
    return signals
