"""Discovery ranking — fold willingness-to-pay and recency into pain so the
Scout can judge how PROMISING a raw signal is, beyond raw frequency.

Used to rank signals within each source (so the per-run cap keeps the strongest)
and to inform the novelty rescue. Dependency-free and cheap — runs over every
signal during a Scout pass.
"""
from datetime import datetime, timezone

import config
from utils.pain import pain_score, wtp_score


def _to_dt(created_at):
    """Parse a signal's authored date (unix seconds, datetime, or ISO 8601).
    Returns None if absent/unparseable — the caller treats that as 'no bonus'."""
    if created_at is None:
        return None
    if isinstance(created_at, datetime):
        return created_at
    # unix seconds (int/float or numeric string)
    try:
        return datetime.fromtimestamp(float(created_at), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        pass
    # ISO 8601 string (GitHub etc.); tolerate a trailing Z
    try:
        return datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def recency_bonus(created_at, now=None):
    """0..RECENCY_MAX, decaying exponentially with age (configurable half-life).
    An unknown/unparseable date yields 0 — no bonus, no penalty."""
    dt = _to_dt(created_at)
    if dt is None:
        return 0.0
    now = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - dt).total_seconds() / 86400.0)
    decay = 0.5 ** (age_days / config.RECENCY_HALFLIFE_DAYS)
    return config.RECENCY_MAX * decay


def discovery_score(signal):
    """Combined promise score for a raw signal dict: pain + paid intent + fresh.
    Higher = a more acute, monetizable, still-live need."""
    text = signal.get("content") or ""
    return (pain_score(text)
            + config.WTP_WEIGHT * wtp_score(text)
            + recency_bonus(signal.get("created_at")))
