"""Unit tests for discovery ranking: recency decay + composite score."""
from datetime import datetime, timedelta, timezone

import pytest

import config
from utils.ranking import _to_dt, discovery_score, recency_bonus

_NOW = datetime(2026, 6, 9, 12, 0, tzinfo=timezone.utc)


def test_to_dt_parses_forms():
    assert _to_dt(None) is None
    assert _to_dt("not a date") is None
    # unix seconds
    assert isinstance(_to_dt(1_700_000_000), datetime)
    # ISO 8601 with Z
    assert _to_dt("2026-06-01T00:00:00Z").year == 2026
    # passthrough datetime
    assert _to_dt(_NOW) == _NOW


def test_recency_bonus_missing_is_zero():
    assert recency_bonus(None) == 0.0
    assert recency_bonus("garbage") == 0.0


def test_recency_bonus_fresh_is_max():
    assert recency_bonus(_NOW, now=_NOW) == pytest.approx(config.RECENCY_MAX)


def test_recency_bonus_halflife_is_half():
    half = _NOW - timedelta(days=config.RECENCY_HALFLIFE_DAYS)
    assert recency_bonus(half, now=_NOW) == pytest.approx(config.RECENCY_MAX / 2,
                                                          rel=1e-3)


def test_recency_bonus_decays_monotonically():
    older = _NOW - timedelta(days=2 * config.RECENCY_HALFLIFE_DAYS)
    newer = _NOW - timedelta(days=config.RECENCY_HALFLIFE_DAYS)
    assert recency_bonus(older, now=_NOW) < recency_bonus(newer, now=_NOW)


def test_discovery_score_combines_signals():
    strong = {"content": "I HATE this, broken and useless, would gladly pay for a fix!"}
    weak = {"content": "minor nitpick about the colors"}
    assert discovery_score(strong) > discovery_score(weak)
    # WTP is weighted into the score
    assert discovery_score({"content": "would pay, currently paying $10/mo"}) > 0
