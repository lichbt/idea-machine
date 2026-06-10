"""Lightweight, dependency-free pain-intensity heuristic for Scout.

Runs over hundreds of raw signals during clustering, so it must be cheap — no
model, no network. Counts frustration markers in the text; a higher score means
more acute, unmet pain. Used to RESCUE novel (low-frequency) but high-pain
signals that the min-cluster popularity filter would otherwise delete: a
genuinely underserved pain is, by definition, mentioned rarely.
"""
import re

# Substring markers (so "crash" also matches "crashes", "frustrat" -> "frustrating").
_MARKERS = (
    "hate", "frustrat", "useless", "broken", "annoying", "terrible",
    "awful", "waste", "scam", "ripoff", "rip off", "garbage", "worst",
    "infuriat", "ridiculous", "disappoint", "unusable", "buggy", "crash",
    "wish there was", "wish it", "why is there no", "no way to", "can't",
    "cannot", "won't let", "refuse", "impossible", "nightmare", "horrible",
    "desperate", "please add", "still no", "deal breaker", "dealbreaker",
    "switched away", "looking for alternative", "alternative to",
)

_SHOUT_RE = re.compile(r"\b[A-Z]{3,}\b")

# Willingness-to-pay markers: language that signals an existing or intended SPEND
# on a fix. A pain someone already pays to relieve (or would) is monetizable —
# the strongest predictor of a fundable idea, distinct from raw frustration.
_WTP_MARKERS = (
    "i'd pay", "id pay", "would pay", "happy to pay", "willing to pay",
    "gladly pay", "take my money", "shut up and take", "worth paying",
    "currently paying", "already paying", "paying for", "pay for a",
    "per month", "/mo", "/month", "a month", "per year", "/yr", "subscription",
    "cancel my", "cancelled my", "canceled my", "switched from", "switched away",
    "too expensive", "overpriced", "not worth the", "free alternative",
    "cheaper alternative", "paywall", "charged me", "refund",
)


def pain_score(text):
    """Return an integer pain-intensity score for a signal's text."""
    if not text:
        return 0
    low = text.lower()
    score = sum(low.count(m) for m in _MARKERS)
    # Emphatic punctuation and shouting are weak corroborating signals (capped).
    score += min(low.count("!"), 3)
    score += min(len(_SHOUT_RE.findall(text)), 3)
    return score


def wtp_score(text):
    """Return an integer willingness-to-pay score: count of spend-intent markers.
    Cheap and dependency-free, like pain_score."""
    if not text:
        return 0
    low = text.lower()
    return sum(low.count(m) for m in _WTP_MARKERS)
