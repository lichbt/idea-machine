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

import config
from agents import scout, swot_researcher, swot_synthesizer, synthesizer, validator
from db.models import (
    Idea,
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
def run_pipeline(retry=False, print_only=False):
    init_db()

    research_results = []
    if retry:
        research_results.extend(_retry_failed_research())

    # Scout -> Validator -> SWOT Research
    scout.run()
    selected_ids = validator.run()
    if selected_ids:
        research_results.extend(swot_researcher.run(selected_ids))

    # Pass 2 (skips failed research) -> Synthesizer (skips KILL)
    analysis_ids = swot_synthesizer.run(research_results)
    synthesizer.run(analysis_ids)

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


def main_run(retry=False, print_only=False):
    """Health check + lockfile guard + pipeline. Lock always released.

    print_only skips the Telegram health check and prints the report instead.
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
        run_pipeline(retry=retry, print_only=print_only)
    finally:
        lock.release()
    return 0


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
    parser.add_argument("--now", action="store_true", help="run pipeline now")
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
    args = parser.parse_args(argv)

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

    if not (args.now or args.retry or args.schedule or args.print_only):
        parser.print_help()
        return 0

    # In print mode the LLM uses the CLI/OpenRouter and there is no Telegram,
    # so only Serper is required.
    if args.print_only:
        if not config.SERPER_API_KEY:
            log.error("Missing required env var: SERPER_API_KEY")
            return 1
    else:
        missing = config.missing_keys()
        if missing:
            log.error("Missing required env vars: %s", ", ".join(missing))
            return 1

    if args.schedule:
        schedule_loop()
        return 0

    return main_run(retry=args.retry, print_only=args.print_only)


if __name__ == "__main__":
    sys.exit(main())
