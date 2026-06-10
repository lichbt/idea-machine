"""Unit tests for the gap-targeting score (the log-scaling fix) on both stores."""
import math

import config
from scrapers import appstore, playstore


def test_appstore_gap_below_audience_floor_is_zero():
    assert appstore._gap_score(None, 3.0) == 0.0
    assert appstore._gap_score(config.GAP_MIN_AUDIENCE - 1, 3.0) == 0.0


def test_appstore_gap_zero_when_top_rated():
    # avg 5.0 -> (5 - avg) == 0 -> no gap regardless of audience
    assert appstore._gap_score(10_000, 5.0) == 0.0


def test_appstore_gap_is_log_scaled():
    # log10(1000) * (5 - 3) = 3 * 2 = 6
    assert appstore._gap_score(1000, 3.0) == math.log10(1000) * 2


def test_appstore_gap_favours_failing_incumbent_over_beloved_leader():
    # THE regression guard: a small failing app must outrank a huge loved one.
    failing = appstore._gap_score(2_000, 3.0)
    beloved = appstore._gap_score(1_000_000, 4.7)
    assert failing > beloved


def test_appstore_is_underserved():
    assert appstore._is_underserved({"ratings": 1000, "avg": 3.0}) is True
    # above the rating ceiling -> not underserved
    assert appstore._is_underserved({"ratings": 1000, "avg": 4.5}) is False
    # below the audience floor -> not underserved
    assert appstore._is_underserved({"ratings": 50, "avg": 2.0}) is False


def test_playstore_installs_parsing():
    assert playstore._installs_to_int("1,000,000+") == 1_000_000
    assert playstore._installs_to_int(None) == 0
    assert playstore._installs_to_int("") == 0


def test_playstore_avg_parsing():
    assert playstore._avg_to_float("4.5") == 4.5
    assert playstore._avg_to_float(None) is None
    assert playstore._avg_to_float("n/a") is None


def test_playstore_gap_log_scaled_and_floored():
    assert playstore._gap_score("100+", 3.0) == 0.0  # below floor
    assert playstore._gap_score("1,000+", 3.0) == math.log10(1000) * 2
