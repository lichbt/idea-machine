"""Product Hunt scraper (Phase 2).

Stubbed for Phase 1: returns no signals so the pipeline runs on Reddit + HN.
Phase 2 will query the official PH GraphQL API for comments on mixed-review
products and surface complaint snippets.
"""
import logging

log = logging.getLogger(__name__)


def scrape(*args, **kwargs):
    log.info("Product Hunt scraper is a Phase 2 stub; returning 0 signals")
    return []
