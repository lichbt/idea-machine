# Product Idea Machine

A multi-agent CLI pipeline that scrapes real pain points, scores them, runs a
two-pass SWOT, and synthesizes differentiated product concepts.

> 📋 **See [`backlog.md`](./backlog.md) for the full change log, CLI reference,
> config knobs, known issues, and current state.** Start there if you forget how
> something works.

**Pipeline:** Scout → Validator → SWOT Research (Pass 1) → SWOT Synthesis (Pass 2)
→ Synthesizer (concepts) → Report. Runs **step by step and resumable**.

## Quick start

```bash
# Always use the venv Python (Python 3.9)
.venv/bin/python run.py --status              # what's pending at each stage (no keys needed)
.venv/bin/python run.py --stage idea          # scout + validate
.venv/bin/python run.py --stage swot --print  # research + synthesize + ideate + report
.venv/bin/python run.py --now --print         # full pipeline (resumable), printed locally
```

Read-only commands need no API keys: `--status`, `--report`, `--analyze`, `--best`, `--html`.
Full CLI reference and everything else lives in [`backlog.md`](./backlog.md).
