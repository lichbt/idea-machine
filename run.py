"""Product Idea Machine — entrypoint.

Pipeline: Scout -> Validator -> SWOT Research (Pass 1) -> SWOT Synthesis
(Pass 2) -> Synthesizer -> Telegram digest.

CLI:
    python run.py --now        run the pipeline immediately
    python run.py --retry      retry failed SWOT research first, then run
    python run.py --analyze    print score distribution, skip pipeline
    python run.py --schedule   start the scheduler loop (VPS deployment)
"""
import argparse
import logging
import sys

from sqlalchemy import exists

import config
from agents import (
    brief,
    opportunity,
    scout,
    swot_researcher,
    swot_synthesizer,
    synthesizer,
    validator,
)
from db.models import (
    Idea,
    RawSignal,
    SwotAnalysis,
    SwotResearch,
    ValidatedIdea,
    get_session,
    init_db,
)
from notifiers import html_report, telegram
from utils.lockfile import LockExists, LockFile

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("run")


# ── digest assembly ────────────────────────────────────────────────────────
def _analysis_view(session, analysis):
    """Flatten a SwotAnalysis (+ pain title + idea) into the dict telegram wants."""
    research = session.query(SwotResearch).get(analysis.swot_research_id)
    validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                 if research else None)
    idea = (session.query(Idea)
            .filter_by(swot_analysis_id=analysis.id)
            .order_by(Idea.id.desc()).first())
    idea_view = None
    if idea:
        idea_view = {
            "name": idea.name,
            "oneliner": idea.oneliner,
            "build_weeks": idea.build_weeks,
            "revenue_model": idea.revenue_model,
            "similarity_flag": idea.similarity_flag,
            "similar_idea_id": idea.similar_idea_id,
        }
    view = {
        "pain_point_title": validated.pain_point_title if validated else "Untitled",
        "verdict": analysis.verdict,
        "overall_score": analysis.overall_score,
        "demand_score": analysis.demand_score,
        "demand_data": analysis.demand_data,
        "score_reliability": analysis.score_reliability,
        "strengths": analysis.strengths,
        "weaknesses": analysis.weaknesses,
        "opportunities": analysis.opportunities,
        "threats": analysis.threats,
        "competitors": analysis.competitors,
        "market_analysis": analysis.market_analysis,
        "biggest_risk": analysis.biggest_risk,
        "biggest_opportunity": analysis.biggest_opportunity,
    }
    return view, idea_view


def _send_digests(analysis_ids):
    """Send a Telegram digest for each PROCEED / PROCEED_WITH_CAUTION analysis."""
    session = get_session()
    sent = 0
    try:
        for aid in analysis_ids:
            analysis = session.query(SwotAnalysis).get(aid)
            if not analysis or analysis.verdict == "KILL":
                continue
            view, idea_view = _analysis_view(session, analysis)
            if telegram.send_digest(view, idea_view):
                sent += 1
    finally:
        session.close()
    log.info("Sent %d Telegram digest(s)", sent)
    return sent


def _print_report(analysis_ids):
    """Print the report to stdout for every analysis from this run, including
    KILL verdicts (so the local report is complete)."""
    session = get_session()
    try:
        if not analysis_ids:
            print("\n(no SWOT analyses produced this run)\n")
            return
        for aid in analysis_ids:
            analysis = session.query(SwotAnalysis).get(aid)
            if not analysis:
                continue
            view, idea_view = _analysis_view(session, analysis)
            print("\n" + "=" * 60)
            print(telegram.format_digest(view, idea_view))
        print("\n" + "=" * 60 + "\n")
    finally:
        session.close()


# ── retry handling ─────────────────────────────────────────────────────────
def _retry_failed_research():
    """Re-run Pass 1 for research rows that previously failed, then return the
    (research_id, status) results for synthesis."""
    session = get_session()
    try:
        failed = (session.query(SwotResearch)
                  .filter(SwotResearch.research_status.in_(["failed", "pending_retry"]))
                  .all())
        idea_ids = [r.validated_idea_id for r in failed]
    finally:
        session.close()

    if not idea_ids:
        log.info("No failed SWOT research to retry")
        return []
    log.info("Retrying %d failed SWOT research row(s)", len(idea_ids))
    return swot_researcher.run(idea_ids)


# ── pipeline ───────────────────────────────────────────────────────────────
def run_pipeline(retry=False, print_only=False, sources=None):
    """Full pipeline, now RESUMABLE: each stage reads its pending work from the
    DB (idempotent), so re-running after an interruption picks up where it left
    off instead of restarting. swot_synthesizer.run() still returns the analyses
    it produced THIS run, so the report/digest scope stays "this run" (no
    re-spamming old ideas)."""
    init_db()

    if retry:
        # Re-run Pass 1 for previously failed research; those rows become
        # complete and get picked up by the DB-driven synthesis below.
        _retry_failed_research()

    # Scout -> Validator -> SWOT Research (Pass 1), all DB-driven.
    scout.run(sources=sources)
    validator.run()
    swot_researcher.run()  # researches the unresearched, passing backlog (capped)

    # Pass 2 (skips failed) -> Synthesizer (skips KILL + pain-duplicates).
    analysis_ids = swot_synthesizer.run()  # returns analyses made this run
    synthesizer.run()

    # Report: print locally, or send PROCEED(_WITH_CAUTION) digests to Telegram.
    if print_only:
        _print_report(analysis_ids)
    else:
        _send_digests(analysis_ids)

    # Always emit an HTML report of this run's analyses.
    if analysis_ids:
        path = html_report.generate(analysis_ids=analysis_ids)
        print(f"HTML report written to: {path}")

    log.info("Pipeline complete")


def main_run(retry=False, print_only=False, sources=None):
    """Health check + lockfile guard + pipeline. Lock always released.

    print_only skips the Telegram health check and prints the report instead.
    sources restricts which scrapers run (None = all).
    """
    if not print_only:
        if telegram.health_check():
            log.info("Telegram health check OK")
        else:
            log.error("Telegram health check FAILED — aborting before any API calls")
            return 1

    lock = LockFile()
    try:
        lock.acquire()
    except LockExists as e:
        log.error("%s", e)
        return 1

    try:
        run_pipeline(retry=retry, print_only=print_only, sources=sources)
    finally:
        lock.release()
    return 0


# ── per-stage commands (run the pipeline step by step) ─────────────────────
def _locked(fn, *args, **kwargs):
    """Run fn under the lockfile so stages can't overlap. Returns 0/1."""
    lock = LockFile()
    try:
        lock.acquire()
    except LockExists as e:
        log.error("%s", e)
        return 1
    try:
        fn(*args, **kwargs)
    finally:
        lock.release()
    return 0


def _emit_report(print_only=False):
    """Report the SWOT analyses produced after a DB-driven SWOT stage. Renders
    HTML for every analysis (newest first) and prints/sends only PROCEED ones."""
    session = get_session()
    try:
        ids = [a.id for a in session.query(SwotAnalysis)
               .order_by(SwotAnalysis.id.desc()).all()]
    finally:
        session.close()
    if print_only:
        _print_report(ids)
    else:
        _send_digests(ids)
    if ids:
        path = html_report.generate(analysis_ids=ids)
        print(f"HTML report written to: {path}")


def run_idea_stage(sources=None):
    """Idea stage: discover + score, checkpoint to the DB. Stops before SWOT."""
    init_db()
    scout.run(sources=sources)
    validator.run()
    log.info("Idea stage complete (scout + validate)")


def run_swot_stage(print_only=False):
    """SWOT stage: research -> synthesize -> ideate -> report, all DB-driven."""
    init_db()
    swot_researcher.run()
    swot_synthesizer.run()
    synthesizer.run()
    _emit_report(print_only=print_only)
    log.info("SWOT stage complete (research + synthesize + ideate + report)")


def _stage_scout(sources=None):
    init_db(); scout.run(sources=sources)


def _stage_validate():
    init_db(); validator.run()


def _stage_research():
    init_db(); swot_researcher.run()


def _stage_synthesize():
    init_db(); swot_synthesizer.run()


def _stage_ideate():
    init_db(); synthesizer.run()


# ── --autopilot (autonomous hunt) ──────────────────────────────────────────
def autopilot(max_rounds=None):
    """Loop discovery -> SWOT -> opportunity scoring in rounds until an idea
    clears the bar (opportunity_score >= AUTOPILOT_PROCEED_SCORE AND
    recommendation == PROCEED), or max_rounds is reached. Each round uses fresh
    feedback seeds, so it explores new categories every loop. Reports the winner
    (or the best found) and writes an HTML report."""
    init_db()
    max_rounds = max_rounds or config.AUTOPILOT_MAX_ROUNDS
    bar = config.AUTOPILOT_PROCEED_SCORE
    best = None
    winner = None

    for rnd in range(1, max_rounds + 1):
        log.info("=== Auto-pilot round %d/%d (proceed bar: score>=%d + PROCEED) ===",
                 rnd, max_rounds, bar)
        try:
            scout.run()              # fresh feedback seeds -> new categories
            validator.run()
            swot_researcher.run()    # DB-driven, capped per round
            swot_synthesizer.run()
            new_idea_ids = synthesizer.run()
        except Exception as e:  # noqa: BLE001 — keep the loop alive across rounds
            log.warning("Round %d pipeline error (%s); continuing", rnd, e)
            continue

        if not new_idea_ids:
            log.info("Round %d produced no new concepts; continuing", rnd)
            continue

        scores = opportunity.run(new_idea_ids)
        for s in scores:
            if best is None or s["score"] > best["score"]:
                best = s
            if s["score"] >= bar and s["recommendation"] == "PROCEED":
                winner = winner or s
        top = scores[0] if scores else None
        if top:
            log.info("Round %d best: %s %d/100 (%s)",
                     rnd, top["name"], top["score"], top["recommendation"])
        if winner:
            log.info("Auto-pilot WINNER in round %d: %s (%d/100)",
                     rnd, winner["name"], winner["score"])
            break

    print("\n" + "=" * 60)
    if winner:
        print(f"AUTO-PILOT ✅ PROCEED — {winner['name']} "
              f"(opportunity {winner['score']}/100)")
        print(f"  {winner['reasoning']}")
    elif best:
        print(f"AUTO-PILOT — no idea cleared score>={bar}+PROCEED in {max_rounds} "
              f"round(s). Best found:")
        print(f"  {best['name']} — {best['recommendation']} {best['score']}/100")
        print(f"  {best['reasoning']}")
        if best.get("fatal_flaw"):
            print(f"  fatal flaw: {best['fatal_flaw']}")
    else:
        print(f"AUTO-PILOT — {max_rounds} round(s) produced no scorable concepts.")
    print("=" * 60 + "\n")

    path = html_report.generate()
    print(f"HTML report written to: {path}")
    log.info("Auto-pilot complete")


# ── --status ───────────────────────────────────────────────────────────────
def pending_counts():
    """Return the count of pending work at each pipeline boundary (the same
    DB-driven ~exists queries the per-stage commands use to select their work)."""
    init_db()
    session = get_session()
    try:
        return {
            "pending_signals": (session.query(RawSignal)
                                .filter_by(status="pending").count()),
            "unresearched": (session.query(ValidatedIdea)
                             .filter(ValidatedIdea.passed.is_(True))
                             .filter(~exists().where(
                                 SwotResearch.validated_idea_id == ValidatedIdea.id))
                             .count()),
            "unsynthesized": (session.query(SwotResearch)
                              .filter(SwotResearch.research_status.in_(
                                  ["complete", "partial"]))
                              .filter(~exists().where(
                                  SwotAnalysis.swot_research_id == SwotResearch.id))
                              .count()),
            "unideated": (session.query(SwotAnalysis)
                          .filter(SwotAnalysis.verdict.in_(
                              ["PROCEED", "PROCEED_WITH_CAUTION"]))
                          .filter(~exists().where(
                              Idea.swot_analysis_id == SwotAnalysis.id))
                          .count()),
        }
    finally:
        session.close()


def status():
    """Print pending-work counts at each pipeline boundary, so you know what to
    run next."""
    c = pending_counts()
    cap = config.MAX_SWOT_PER_RUN
    print("\n=== Pipeline Status (pending work at each boundary) ===\n")
    print(f"  pending signals        -> --validate : {c['pending_signals']}")
    print(f"  passed, unresearched   -> --research : {c['unresearched']}  "
          f"(next run does up to {cap})")
    print(f"  research, unsynthesized-> --synthesize: {c['unsynthesized']}")
    print(f"  analyses, unideated    -> --ideate   : {c['unideated']}")
    print()


# ── --funnel ───────────────────────────────────────────────────────────────
def funnel():
    """Show where ideas die at each stage of the pipeline, so you can see if a
    threshold is too strict and tune it."""
    from collections import Counter
    init_db()
    session = get_session()
    try:
        sig = Counter(s.status for s in session.query(RawSignal).all())
        vi_total = session.query(ValidatedIdea).count()
        vi_passed = (session.query(ValidatedIdea)
                     .filter(ValidatedIdea.passed.is_(True)).count())
        res = Counter(r.research_status for r in session.query(SwotResearch).all())
        verdicts = Counter(a.verdict for a in session.query(SwotAnalysis).all())
        demand_kills = (session.query(SwotAnalysis)
                        .filter(SwotAnalysis.verdict == "KILL")
                        .filter(SwotAnalysis.demand_score.isnot(None))
                        .filter(SwotAnalysis.demand_score < config.DEMAND_KILL_BELOW)
                        .count())
        ideas_total = session.query(Idea).count()
        recs = Counter(i.opportunity_recommendation
                       for i in session.query(Idea).all()
                       if i.opportunity_recommendation)
        cleared = (session.query(Idea)
                   .filter(Idea.opportunity_score >= config.AUTOPILOT_PROCEED_SCORE)
                   .filter(Idea.opportunity_recommendation == "PROCEED").count())
    finally:
        session.close()

    def line(label, n, note=""):
        print(f"  {label:<34} {n:>5}   {note}")

    print("\n=== Idea Funnel (where ideas die) ===\n")
    print(" SCOUT")
    line("raw signals scraped", sum(sig.values()))
    line("· still pending", sig.get("pending", 0))
    print(" VALIDATOR")
    line("validated (scored)", vi_total)
    line(f"· passed gate (>= {config.VALIDATION_THRESHOLD})", vi_passed,
         f"DROPPED {vi_total - vi_passed}")
    print(" SWOT PASS 1 (research)")
    line("· complete", res.get("complete", 0))
    line("· partial / failed", res.get("partial", 0) + res.get("failed", 0))
    print(" SWOT PASS 2 (verdict)")
    line("· PROCEED", verdicts.get("PROCEED", 0))
    line("· PROCEED_WITH_CAUTION", verdicts.get("PROCEED_WITH_CAUTION", 0))
    line("· KILL", verdicts.get("KILL", 0),
         f"({demand_kills} by demand gate < {config.DEMAND_KILL_BELOW})")
    print(" CONCEPTS + OPPORTUNITY JUDGE")
    line("ideas generated", ideas_total)
    line("· PROCEED", recs.get("PROCEED", 0))
    line("· ITERATE", recs.get("ITERATE", 0))
    line("· DROP", recs.get("DROP", 0))
    line(f"· cleared bar (>= {config.AUTOPILOT_PROCEED_SCORE} + PROCEED)", cleared,
         "<- ready to build")
    print()


# ── --analyze ──────────────────────────────────────────────────────────────
def _bucketize(values, edges):
    counts = [0] * (len(edges) + 1)
    for v in values:
        placed = False
        for i, edge in enumerate(edges):
            if v < edge:
                counts[i] += 1
                placed = True
                break
        if not placed:
            counts[-1] += 1
    return counts


def analyze():
    init_db()
    session = get_session()
    try:
        val_scores = [v.total_score for v in session.query(ValidatedIdea).all()
                      if v.total_score is not None]
        swot_scores = [a.overall_score for a in session.query(SwotAnalysis).all()
                       if a.overall_score is not None]
        verdicts = {}
        for a in session.query(SwotAnalysis).all():
            verdicts[a.verdict] = verdicts.get(a.verdict, 0) + 1
    finally:
        session.close()

    edges = [25, 50, 65, 75, 90]
    labels = ["0-24", "25-49", "50-64", "65-74", "75-89", "90-100"]

    print("\n=== Score Distribution Report ===")
    print(f"\nValidator total_score (n={len(val_scores)}), "
          f"threshold={config.VALIDATION_THRESHOLD}")
    for label, count in zip(labels, _bucketize(val_scores, edges)):
        print(f"  {label:>7}: {'#' * count} {count}")

    print(f"\nSWOT overall_score (n={len(swot_scores)}), "
          f"proceed>={config.SWOT_PROCEED_THRESHOLD}, "
          f"caution>={config.SWOT_CAUTION_THRESHOLD}")
    for label, count in zip(labels, _bucketize(swot_scores, edges)):
        print(f"  {label:>7}: {'#' * count} {count}")

    print("\nVerdicts:")
    for verdict, count in sorted(verdicts.items()):
        print(f"  {verdict}: {count}")
    print()


# ── --best (cross-run leaderboard) ─────────────────────────────────────────
def best(limit=10):
    """Rank all PROCEED / PROCEED_WITH_CAUTION ideas across history by score.
    Prints a leaderboard and renders the top ones to HTML."""
    init_db()
    session = get_session()
    try:
        rows = (session.query(SwotAnalysis)
                .filter(SwotAnalysis.verdict.in_(
                    ["PROCEED", "PROCEED_WITH_CAUTION"]))
                .order_by(SwotAnalysis.overall_score.desc())
                .limit(limit).all())
        entries = []
        for a in rows:
            research = session.query(SwotResearch).get(a.swot_research_id)
            validated = (session.query(ValidatedIdea).get(research.validated_idea_id)
                         if research else None)
            idea = (session.query(Idea)
                    .filter_by(swot_analysis_id=a.id)
                    .order_by(Idea.id.desc()).first())
            entries.append((a, validated, idea))
        ids = [a.id for a, _, _ in entries]
    finally:
        session.close()

    print("\n=== BEST IDEAS LEADERBOARD (PROCEED / CAUTION, top %d) ===\n" % limit)
    if not entries:
        print("  No PROCEED or PROCEED_WITH_CAUTION ideas in the DB yet.")
        print("  (Add better sources — e.g. Reddit creds — to surface winners.)\n")
        return

    print(f"  {'#':>2}  {'SCORE':>5}  {'REL':>4}  {'VERDICT':<20}  IDEA / PAIN POINT")
    print("  " + "-" * 76)
    for rank, (a, validated, idea) in enumerate(entries, 1):
        pain = (validated.pain_point_title if validated else "?")[:44]
        name = idea.name if idea else "(no concept)"
        print(f"  {rank:>2}  {a.overall_score:>5}  {a.score_reliability or '?':>4}  "
              f"{(a.verdict or '').replace('_', ' '):<20}  {name} — {pain}")
    print()

    path = html_report.generate(analysis_ids=ids)
    print(f"HTML leaderboard written to: {path}\n")


# ── --schedule ─────────────────────────────────────────────────────────────
def schedule_loop():
    import schedule
    import time

    day = config.SCHEDULE_DAY.lower()
    getattr(schedule.every(), day).at(config.SCHEDULE_TIME).do(main_run)
    log.info("Scheduler started: every %s at %s", day, config.SCHEDULE_TIME)
    while True:
        schedule.run_pending()
        time.sleep(30)


# ── CLI ────────────────────────────────────────────────────────────────────
def main(argv=None):
    parser = argparse.ArgumentParser(description="Product Idea Machine")
    parser.add_argument("--now", action="store_true", help="run the full pipeline now")
    parser.add_argument("--retry", action="store_true",
                        help="retry failed SWOT research first, then run")
    parser.add_argument("--analyze", action="store_true",
                        help="print score distribution and exit")
    parser.add_argument("--schedule", action="store_true",
                        help="start the scheduler loop")
    parser.add_argument("--print", dest="print_only", action="store_true",
                        help="print the report to stdout instead of sending "
                             "Telegram (skips the Telegram health check)")
    parser.add_argument("--html", nargs="?", const="", metavar="PATH",
                        help="render existing SWOT analyses to an HTML file and "
                             "exit (optional output PATH; default reports/)")
    parser.add_argument("--best", nargs="?", const=10, type=int, metavar="N",
                        help="show the top-N PROCEED/CAUTION ideas across all "
                             "runs and exit (default N=10)")
    parser.add_argument("--sources", metavar="A,B,C",
                        help="comma-separated scrapers to run (default all): "
                             "reddit,hackernews,producthunt,appstore,playstore,"
                             "appsumo,github,trustpilot")
    # ── step-by-step controls (run the pipeline one stage at a time) ──
    parser.add_argument("--status", action="store_true",
                        help="print pending-work counts per stage and exit")
    parser.add_argument("--funnel", action="store_true",
                        help="print where ideas die at each stage and exit")
    parser.add_argument("--stage", choices=["idea", "swot"], metavar="STAGE",
                        help="run a coarse stage: 'idea'=scout+validate, "
                             "'swot'=research+synthesize+ideate+report")
    parser.add_argument("--scout", action="store_true", help="run Scout only")
    parser.add_argument("--validate", action="store_true", help="run Validator only")
    parser.add_argument("--research", action="store_true",
                        help="run SWOT Pass-1 on passing, unresearched ideas")
    parser.add_argument("--synthesize", action="store_true",
                        help="run SWOT Pass-2 on unsynthesized research")
    parser.add_argument("--ideate", action="store_true",
                        help="generate concepts for unideated PROCEED/CAUTION analyses")
    parser.add_argument("--report", action="store_true",
                        help="render HTML for all analyses and exit")
    parser.add_argument("--brief", nargs="?", const=-1, type=int, metavar="IDEA_ID",
                        help="generate an MVP build brief for an idea (default: "
                             "the highest-opportunity idea) and exit")
    parser.add_argument("--score", nargs="?", const="new", choices=["new", "all"],
                        metavar="WHICH",
                        help="score ideas with the Opportunity Judge: 'new' "
                             "(default, unscored only) or 'all' (re-score every "
                             "idea), print the ranking, and exit")
    parser.add_argument("--autopilot", nargs="?", const=config.AUTOPILOT_MAX_ROUNDS,
                        type=int, metavar="ROUNDS",
                        help="autonomous hunt: loop discovery->SWOT->opportunity "
                             "scoring for up to N rounds (default %d), stopping at "
                             "the first idea scoring >=%d + PROCEED"
                             % (config.AUTOPILOT_MAX_ROUNDS,
                                config.AUTOPILOT_PROCEED_SCORE))
    args = parser.parse_args(argv)

    # ── read-only commands: no keys, no lock ──
    if args.analyze:
        analyze()
        return 0
    if args.best is not None:
        best(limit=args.best)
        return 0
    if args.html is not None:
        init_db()
        path = html_report.generate(path=args.html or None)
        print(f"HTML report written to: {path}")
        return 0
    if args.status:
        status()
        return 0
    if args.funnel:
        funnel()
        return 0
    if args.report:
        init_db()
        path = html_report.generate()
        print(f"HTML report written to: {path}")
        return 0
    if args.score is not None:
        init_db()

        def _do_score():
            if args.score == "all":
                session = get_session()
                try:
                    ids = [i.id for i in session.query(Idea).all()]
                finally:
                    session.close()
                results = opportunity.run(ids)
            else:
                results = opportunity.run()  # unscored only
            bar = config.AUTOPILOT_PROCEED_SCORE
            print(f"\n=== Opportunity scores (bar: >= {bar} + PROCEED) ===\n")
            if not results:
                print("  (no ideas to score)\n")
                return
            winners = 0
            for r in results:
                win = r["score"] >= bar and r["recommendation"] == "PROCEED"
                winners += win
                print(f"  {r['score']:>3}/100  {r['recommendation']:<8} "
                      f"{r['name']}{'   <- WINNER' if win else ''}")
            print(f"\n{winners} idea(s) cleared the bar.\n")
        return _locked(_do_score)
    if args.brief is not None:
        init_db()
        iid = brief.best_idea_id() if args.brief == -1 else args.brief

        def _do_brief():
            if not iid:
                print("No ideas to brief yet.")
                return
            path, b = brief.generate(iid)
            if path:
                print(f"Build brief written to: {path}")
                print(f"  MVP: {b.get('mvp_scope', '')}")
            else:
                print("Brief generation failed.")
        return _locked(_do_brief)

    sources = ([s.strip() for s in args.sources.split(",") if s.strip()]
               if args.sources else None)
    fine = (args.scout, args.validate, args.research, args.synthesize, args.ideate)
    if not (args.now or args.retry or args.schedule or args.print_only
            or args.stage or any(fine) or args.autopilot is not None):
        parser.print_help()
        return 0

    # Key checks: the Telegram path (full run / swot stage / schedule, all
    # WITHOUT --print) needs the Telegram keys; every other action just needs
    # Serper (for research) and the local LLM.
    sends_telegram = (not args.print_only) and (
        args.now or args.retry or args.schedule or args.stage == "swot")
    if sends_telegram:
        missing = config.missing_keys()
        if missing:
            log.error("Missing required env vars: %s", ", ".join(missing))
            return 1
    elif not (config.SERPER_API_KEY or config.BRAVE_API_KEY):
        log.error("Missing a web-search key: set SERPER_API_KEY or BRAVE_API_KEY")
        return 1

    if args.schedule:
        schedule_loop()
        return 0

    # ── autonomous hunt ──
    if args.autopilot is not None:
        return _locked(autopilot, args.autopilot)

    # ── coarse stages ──
    if args.stage == "idea":
        return _locked(run_idea_stage, sources)
    if args.stage == "swot":
        return _locked(run_swot_stage, print_only=args.print_only)

    # ── fine-grained stages: run the requested ones in pipeline order, one lock ──
    if any(fine):
        def _run_fine():
            if args.scout:
                _stage_scout(sources)
            if args.validate:
                _stage_validate()
            if args.research:
                _stage_research()
            if args.synthesize:
                _stage_synthesize()
            if args.ideate:
                _stage_ideate()
        return _locked(_run_fine)

    # ── full pipeline (--now / --retry / --print) ──
    return main_run(retry=args.retry, print_only=args.print_only, sources=sources)


if __name__ == "__main__":
    sys.exit(main())
