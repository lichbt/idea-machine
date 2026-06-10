"""Unit tests for the dependency-free pain + willingness-to-pay heuristics."""
from utils.pain import pain_score, wtp_score


def test_pain_score_empty():
    assert pain_score("") == 0
    assert pain_score(None) == 0


def test_pain_score_counts_markers():
    # hate, broken, useless -> 3 distinct markers
    assert pain_score("I hate this broken useless app") >= 3


def test_pain_score_punctuation_and_shout_capped():
    # exclamation count caps at +3, SHOUT count caps at +3
    many_bangs = pain_score("ok" + "!" * 10)
    assert many_bangs == 3  # no markers, only the capped ! bonus
    shout = pain_score("THIS APP CRASHES CONSTANTLY OFTEN")
    # "crash" marker (1) + shout cap (3) at least
    assert shout >= 4


def test_wtp_score_empty():
    assert wtp_score("") == 0
    assert wtp_score(None) == 0


def test_wtp_score_detects_spend_intent():
    assert wtp_score("I would pay for this, currently paying $15/mo") >= 2
    assert wtp_score("happy to pay, take my money") >= 1


def test_wtp_score_ignores_neutral_text():
    assert wtp_score("this app is fine and works well") == 0
