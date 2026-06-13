"""DB-logic tests on a throwaway SQLite DB: migration idempotency, the pending-
work ~exists queries, and the resumable DB-driven research selection."""
import config


def test_migration_adds_opportunity_columns_idempotently(temp_db):
    from sqlalchemy import inspect

    # second init_db must be a no-op, not an error
    temp_db.init_db()
    insp = inspect(temp_db.get_engine())
    cols = {c["name"] for c in insp.get_columns("ideas")}
    assert {"opportunity_score", "opportunity_recommendation",
            "opportunity_scores", "opportunity_reasoning"} <= cols


def test_pending_counts(temp_db):
    import run
    from db.models import (
        Idea, RawSignal, SwotAnalysis, SwotResearch, ValidatedIdea, get_session,
    )

    s = get_session()
    # one pending signal
    s.add(RawSignal(source="x", content="c", content_hash="h1", status="pending"))
    # passing idea, no research -> unresearched
    s.add(ValidatedIdea(passed=True, total_score=80))
    # passing idea + complete research, no analysis -> unsynthesized
    vi2 = ValidatedIdea(passed=True, total_score=70); s.add(vi2); s.flush()
    s.add(SwotResearch(validated_idea_id=vi2.id, research_status="complete"))
    # passing idea + research + PROCEED analysis, no idea -> unideated
    vi3 = ValidatedIdea(passed=True, total_score=60); s.add(vi3); s.flush()
    sr3 = SwotResearch(validated_idea_id=vi3.id, research_status="complete")
    s.add(sr3); s.flush()
    s.add(SwotAnalysis(swot_research_id=sr3.id, verdict="PROCEED", overall_score=80))
    # a KILL analysis must NOT count as unideated
    vi4 = ValidatedIdea(passed=True, total_score=50); s.add(vi4); s.flush()
    sr4 = SwotResearch(validated_idea_id=vi4.id, research_status="complete")
    s.add(sr4); s.flush()
    sa4 = SwotAnalysis(swot_research_id=sr4.id, verdict="KILL", overall_score=30)
    s.add(sa4); s.flush()
    # an analysis that already has an Idea must NOT count as unideated
    vi5 = ValidatedIdea(passed=True, total_score=55); s.add(vi5); s.flush()
    sr5 = SwotResearch(validated_idea_id=vi5.id, research_status="complete")
    s.add(sr5); s.flush()
    sa5 = SwotAnalysis(swot_research_id=sr5.id, verdict="PROCEED", overall_score=78)
    s.add(sa5); s.flush()
    s.add(Idea(swot_analysis_id=sa5.id, name="Existing"))
    s.commit()
    s.close()

    c = run.pending_counts()
    assert c["pending_signals"] == 1
    # vi(80), vi2..vi5 all have research -> only vi is unresearched
    assert c["unresearched"] == 1
    # sr (vi2's) is the only complete research without an analysis
    assert c["unsynthesized"] == 1
    # only sa3 is PROCEED-without-Idea (sa4 KILL, sa5 has an Idea)
    assert c["unideated"] == 1


def test_research_selection_is_passing_unresearched_capped_ordered(temp_db, monkeypatch):
    from db.models import SwotResearch, ValidatedIdea, get_session
    from agents import swot_researcher

    s = get_session()
    for sc in [50, 90, 80, 70, 60, 40]:          # 6 passing, unresearched
        s.add(ValidatedIdea(passed=True, total_score=sc))
    done = ValidatedIdea(passed=True, total_score=100)  # passing but researched
    s.add(done); s.flush()
    s.add(SwotResearch(validated_idea_id=done.id, research_status="complete"))
    s.add(ValidatedIdea(passed=False, total_score=99))  # not passed -> ignored
    s.commit()
    s.close()

    picked = []

    def fake_research(idea):
        picked.append(idea.total_score)
        ss = get_session()
        row = SwotResearch(validated_idea_id=idea.id, research_status="complete")
        ss.add(row); ss.commit(); rid = row.id; ss.close()
        return rid

    monkeypatch.setattr(swot_researcher, "research", fake_research)
    swot_researcher.run()  # None -> DB-driven selection

    # top MAX_SWOT_PER_RUN unresearched passing ideas, by score desc;
    # the researched 100 and the not-passed 99 are excluded, and 40 falls off.
    assert len(picked) == config.MAX_SWOT_PER_RUN
    assert sorted(picked, reverse=True) == [90, 80, 70, 60, 50]


def test_backlog_rows_lists_unresearched_passed_only(temp_db):
    import run
    from db.models import RawSignal, SwotResearch, ValidatedIdea, get_session

    s = get_session()
    sig = RawSignal(source="ecosystem", content="c", content_hash="hb1",
                    status="processed")
    s.add(sig); s.flush()
    s.add(ValidatedIdea(passed=True, total_score=74, signal_id=sig.id,
                        pain_point_title="Open gap"))
    done = ValidatedIdea(passed=True, total_score=90,
                         pain_point_title="Already researched")
    s.add(done); s.flush()
    s.add(SwotResearch(validated_idea_id=done.id, research_status="complete"))
    s.add(ValidatedIdea(passed=False, total_score=99,
                        pain_point_title="Failed validation"))
    s.commit()
    s.close()

    rows = run.backlog_rows(limit=10)
    assert [r["title"] for r in rows] == ["Open gap"]
    assert rows[0]["source"] == "ecosystem"
    assert rows[0]["score"] == 74


def test_research_cli_accepts_explicit_ids(temp_db, monkeypatch):
    from agents import swot_researcher
    from db.models import SwotResearch, ValidatedIdea, get_session

    s = get_session()
    ids = []
    for sc in [80, 70, 60]:
        vi = ValidatedIdea(passed=True, total_score=sc,
                           pain_point_title=f"p{sc}")
        s.add(vi); s.flush()
        ids.append(vi.id)
    s.commit()
    s.close()

    picked = []

    def fake_research(idea):
        picked.append(idea.total_score)
        ss = get_session()
        row = SwotResearch(validated_idea_id=idea.id, research_status="complete")
        ss.add(row); ss.commit(); rid = row.id; ss.close()
        return rid

    monkeypatch.setattr(swot_researcher, "research", fake_research)
    # hand-pick the 80 and 60 scorers; the 70 must be untouched
    swot_researcher.run(validated_idea_ids=[ids[0], ids[2]])
    assert sorted(picked) == [60, 80]
