"""Unit tests for the SWOT scoring upgrades: confidence shrinkage + the
adversarial (downgrade-only) verdict reconciliation."""
import config
from agents import swot_synthesizer as sw


def test_shrink_high_confidence_unchanged():
    assert sw._shrink(80, "high") == 80
    assert sw._shrink(20, "High") == 20


def test_shrink_pulls_toward_50_by_confidence():
    # medium = 0.7, low = 0.4 toward the neutral 50
    assert sw._shrink(80, "medium") == 50 + 0.7 * 30
    assert sw._shrink(80, "low") == 50 + 0.4 * 30
    assert sw._shrink(20, "low") == 50 + 0.4 * -30


def test_shrink_neutral_score_is_invariant():
    for conf in ("high", "medium", "low", None, "garbage"):
        assert sw._shrink(50, conf) == 50


def test_weighted_score_downweights_low_confidence_quadrant():
    hi = {n: {"score": 90, "confidence": "high"} for n in config.SWOT_WEIGHTS}
    lo = {n: {"score": 90, "confidence": "low"} for n in config.SWOT_WEIGHTS}
    # same raw scores, but low-confidence shrinks toward 50 -> lower total
    assert sw._weighted_score(lo) < sw._weighted_score(hi)
    assert sw._weighted_score(hi) == 90


def test_apply_challenge_downgrades_only():
    kill = {"recommended_adjustment": "downgrade_to_kill", "fatal_flaw": "saturated"}
    caution = {"recommended_adjustment": "downgrade_to_caution", "fatal_flaw": "thin"}
    keep = {"recommended_adjustment": "keep"}

    v, note = sw._apply_challenge("PROCEED", kill)
    assert v == "KILL" and note

    v, note = sw._apply_challenge("PROCEED", caution)
    assert v == "PROCEED_WITH_CAUTION" and note

    # keep / None -> unchanged, no note
    assert sw._apply_challenge("PROCEED", keep) == ("PROCEED", "")
    assert sw._apply_challenge("PROCEED", None) == ("PROCEED", "")

    # downgrade-only: cannot upgrade a KILL up to caution
    assert sw._apply_challenge("KILL", caution) == ("KILL", "")
