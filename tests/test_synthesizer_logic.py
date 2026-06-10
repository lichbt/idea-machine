"""Unit tests for the synthesizer's pure helpers: SWOT/competitor/complaint
context blocks and the pain-level dedup (embeddings stubbed for speed)."""
from types import SimpleNamespace

from agents import synthesizer


def test_prose_extracts_from_dict_or_str():
    assert synthesizer._prose({"prose": "hello"}) == "hello"
    assert synthesizer._prose("plain") == "plain"
    assert synthesizer._prose(None) == ""
    assert synthesizer._prose({}) == ""


def test_swot_block_empty_when_no_data():
    a = SimpleNamespace(strengths=None, weaknesses=None, threats=None)
    assert synthesizer._swot_block(a) == ""


def test_swot_block_includes_present_quadrants():
    a = SimpleNamespace(strengths={"prose": "strong demand"},
                        weaknesses={"prose": "marketplace problem"},
                        threats=None)
    block = synthesizer._swot_block(a)
    assert "STRENGTH: strong demand" in block
    assert "WEAKNESS: marketplace problem" in block
    assert "THREAT" not in block


def test_competitor_block_names_and_weaknesses():
    a = SimpleNamespace(competitors=[
        {"name": "Rover", "core_weakness": "no accountability for no-shows"},
        {"name": "", "core_weakness": "ignored (no name)"},
    ])
    block = synthesizer._competitor_block(a)
    assert "Rover" in block and "no accountability" in block
    assert "ignored" not in block  # nameless competitor skipped


def test_competitor_block_empty_when_none():
    assert synthesizer._competitor_block(SimpleNamespace(competitors=None)) == ""


def test_complaint_block_keeps_only_low_star():
    a = SimpleNamespace(demand_data={"prior_apps": [
        {"reviews": [{"rating": 1, "text": "loses my data"},
                     {"rating": 5, "text": "love it"}]}]})
    block = synthesizer._complaint_block(a)
    assert "loses my data" in block
    assert "love it" not in block


def test_complaint_block_empty_without_demand_data():
    assert synthesizer._complaint_block(SimpleNamespace(demand_data=None)) == ""


def test_existing_block():
    assert synthesizer._existing_block([]) == ""
    block = synthesizer._existing_block(["AppA: does X", "AppB: does Y"])
    assert "AppA: does X" in block and "AppB: does Y" in block


def test_dedup_by_pain_collapses_same_pain(monkeypatch):
    # Stub embeddings: two pains are "similar" iff they share their first word.
    def fake_most_similar(text, candidates):
        if not candidates or not text:
            return (None, 0.0)
        head = text.split()[0].lower()
        for i, c in enumerate(candidates):
            if c and c.split()[0].lower() == head:
                return (i, 0.9)  # above CONCEPT_SIMILARITY_THRESHOLD (0.6)
        return (None, 0.0)

    monkeypatch.setattr(synthesizer, "most_similar", fake_most_similar)

    items = [
        (101, 62, "invoicing freelancers paywall"),
        (102, 58, "invoicing apps lock features"),   # dup of 101 (same head word)
        (103, 60, "mileage tracker broken"),          # distinct
    ]
    kept, skipped = synthesizer._dedup_by_pain(items)
    # highest-scoring of each pain cluster survives; mileage is its own cluster
    assert set(kept) == {101, 103}
    assert skipped == [(102, 101)]
