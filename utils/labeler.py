"""LLM cluster-labeling — distill each selected raw signal into a crisp, one-line
PAIN STATEMENT prepended above the raw evidence.

Raw signals are noisy (profane reviews, rambling forum posts, issue dumps). A
crisp lead sentence lets the Validator score the underlying PROBLEM rather than
the phrasing. Bounded to the post-cap selection and batched into a SINGLE LLM
call (not one per signal) to avoid many flaky sequential calls. Degrades
gracefully: any failure leaves the original content untouched.
"""
import logging

import config
from utils.claude_caller import call_json

log = logging.getLogger(__name__)

_SYSTEM = (
    "You distill messy user complaints into crisp product pain statements. "
    "Reply with ONLY valid JSON, no prose."
)


def _prompt(items):
    blob = "\n".join(f"{i}. {text}" for i, text in items)
    return f"""Below are raw user complaints/snippets, each numbered. For EACH, write
ONE crisp sentence naming the underlying PRODUCT PAIN (the unmet need) — strip app
names, profanity, and noise, but keep the user's actual problem. Do not invent
needs that aren't in the text.

{blob}

Return JSON exactly: {{"labels": [{{"i": <number>, "pain": "<one sentence>"}}, ...]}}"""


def label_clusters(signals, max_chars=300):
    """Prepend an LLM-distilled pain statement to each selected signal's content.
    Returns the same list (mutated). No-op when disabled, empty, or on failure."""
    if not signals or not config.CLUSTER_LABELING:
        return signals

    items = [(idx, (s.get("content") or "")[:max_chars])
             for idx, s in enumerate(signals)]
    try:
        result = call_json(_prompt(items), system=_SYSTEM)
        labels = result.get("labels") if isinstance(result, dict) else None
    except Exception as e:  # noqa: BLE001 — labeling must never break discovery
        log.warning("Cluster labeling failed (%s); keeping raw content", e)
        return signals
    if not labels:
        log.info("Cluster labeling returned no labels; keeping raw content")
        return signals

    by_i = {}
    for entry in labels:
        try:
            by_i[int(entry["i"])] = str(entry["pain"]).strip()
        except (KeyError, TypeError, ValueError):
            continue

    labeled = 0
    for idx, s in enumerate(signals):
        pain = by_i.get(idx)
        if pain:
            s["content"] = f"{pain}\n\n--- raw evidence ---\n{s.get('content', '')}"
            labeled += 1
    log.info("Cluster labeling: %d/%d signals labeled", labeled, len(signals))
    return signals
