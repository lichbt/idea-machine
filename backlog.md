# Product Idea Machine — Backlog & Change Log

A running reference of what's been built, why, how to operate it, and what's left.
Newest work at the top. Last updated: **2026-06-09**.

> **Pipeline:** Scout → Validator → SWOT Research (Pass 1) → SWOT Synthesis (Pass 2)
> → Synthesizer (concepts) → Report (HTML / Telegram).
> **Run everything with `.venv/bin/python`** (Python 3.9 — no 3.10+ syntax).
> The DB chain: `RawSignal → ValidatedIdea → SwotResearch → SwotAnalysis → Idea`.

---

## 0. CLI quick reference (how to run it now)

The pipeline is now **step-by-step and resumable** — you don't have to run it all
in one shot (which used to get killed mid-way).

```bash
# See what's pending at each stage (read-only, no keys needed)
.venv/bin/python run.py --status

# Run the two halves separately, checkpointing to the DB between them:
.venv/bin/python run.py --stage idea          # scout + validate
.venv/bin/python run.py --stage swot --print  # research + synthesize + ideate + report (printed)

# Or one fine-grained stage at a time (each reads its own pending work from the DB):
.venv/bin/python run.py --scout
.venv/bin/python run.py --validate
.venv/bin/python run.py --research            # SWOT Pass 1 on passing, unresearched ideas (cap 5/run)
.venv/bin/python run.py --synthesize          # SWOT Pass 2 on unsynthesized research
.venv/bin/python run.py --ideate              # concepts for unideated PROCEED/CAUTION analyses

# Reports & analysis (read-only)
.venv/bin/python run.py --report              # render HTML for all analyses
.venv/bin/python run.py --best 10             # top-N PROCEED/CAUTION leaderboard
.venv/bin/python run.py --analyze             # score distribution histogram
.venv/bin/python run.py --funnel              # where ideas die at each stage (tune thresholds)
.venv/bin/python run.py --html                # render all analyses to HTML

# Build brief — turn a winning idea into a concrete MVP plan (markdown + DB)
.venv/bin/python run.py --brief               # the highest-opportunity idea
.venv/bin/python run.py --brief 21            # a specific idea by id

# Full pipeline (now resumable — re-run after a kill and it picks up from the DB)
.venv/bin/python run.py --now --print         # local run, prints report, no Telegram
.venv/bin/python run.py --now                 # full run, sends Telegram (needs TELEGRAM_* keys)
.venv/bin/python run.py --retry               # re-run failed Pass-1 research first, then run
.venv/bin/python run.py --sources reddit,github,appstore --stage idea   # restrict scrapers

# Autonomous hunt — loop until a winner (or N rounds), scored by the Opportunity Judge
.venv/bin/python run.py --autopilot       # up to AUTOPILOT_MAX_ROUNDS (5) rounds
.venv/bin/python run.py --autopilot 3     # cap at 3 rounds
```

**Key rules:** stages run under a lockfile (no overlap). Read-only commands
(`--status`, `--report`, `--analyze`, `--best`, `--html`) need no API keys. The
`--research` stage needs `SERPER_API_KEY`. Only the Telegram path (`--now`,
`--stage swot` without `--print`, `--schedule`) needs `TELEGRAM_*`.

---

## 1. LLM backend (switched off 9router → Claude CLI)

- **Backend is the Claude CLI** (`claude -p`) — **no LLM API calls.** As of 2026-06-09 the
  CODE default is `LLM_BACKEND=cli` (not just the `.env` override), so the project routes ALL
  LLM through the CLI even if the `.env` line is removed; backend order is `['cli']` with no
  HTTP fallback. `config.LLM_BACKEND` still accepts `auto` / `openai` to opt back into the
  OpenAI-compatible / OpenRouter HTTP paths, but those are never used by default.
  - **"No API" = the LLM layer only.** Data-source APIs are separate and still used: Serper
    (Google search for SWOT research + Reddit), iTunes / Google-Play store APIs, GitHub Issues.
  - The 9router gateway (OpenAI-compatible, `localhost:20128`) remains wired but disabled.
  - Why off 9router: most of its model namespaces were unauthorized (401/402/429);
    only `openclaw-combo`, `ag/*`, `cx/*`, `opencode`, `chinese` worked. `ag/gemini-3-flash`
    benchmarked fastest (~3.3s) if we ever go back.
- **CLI reliability fix (important):** `utils/claude_caller.py` now pipes the prompt to
  `claude -p` via **STDIN** instead of as an argv argument. Large prompts (a SWOT
  synthesis loaded with prior-art apps + reviews) used to overflow the OS arg limit
  and **fail every time** on exactly the big ideas. Stdin has no such limit.
- **Known flakiness:** rapid *sequential* `claude -p` calls still intermittently exit 1
  (transient). Mitigated by `CLAUDE_MAX_RETRIES=3`. Batch jobs (Pass 2 over many ideas)
  are slow (30–90s each) — prefer the step-by-step stages over one monolithic run.

---

## 2. Discovery / search improvements (surface better, less-saturated ideas)

All take effect on the **next Scout run** (existing signals unaffected).

1. **Gap-targeting (app stores).** Store scrapers rank apps by "big audience + low
   rating = failing incumbent," and tag such apps `UNDERSERVED`.
   - **Fix:** the gap score was `ratings × (5−avg)` — dominated by raw popularity, so a
     beloved 4.7★ leader outranked a failing 3.0★ incumbent 75×. Now **log-scaled**:
     `log10(ratings) × (5−avg)`, so dissatisfaction drives the ranking.
   - `GAP_MIN_AUDIENCE=500`, `GAP_RATING_CEILING=3.7`. (`scrapers/appstore.py`, `playstore.py`)
2. **Novelty rescue.** A sub-threshold cluster (rare mention) is kept if its language
   shows strong pain (`utils/pain.py:pain_score ≥ PAIN_KEEP_THRESHOLD`).
   - **Fix:** threshold was `3` → rescued ~every singleton (271 rescues / 0 drops,
     effectively disabling the popularity filter). Now **`7`** (35 rescues / ~810 drops).
3. **Feedback-driven seeds.** `agents/seed_planner.py` reads verdict history and asks the
   LLM for FRESH app-store category seeds each run — leans toward winners, avoids saturated
   losers, and avoids categories already tried (breaks the "dedup deadlock" where re-scraping
   fixed sources yields ~no new signals). `FEEDBACK_SEEDS=true`, `FEEDBACK_SEED_COUNT=8`.
4. **Willingness-to-pay + recency ranking.** New `discovery_score = pain + WTP_WEIGHT·wtp +
   recency_bonus` ranks signals **within each source** so the per-run cap keeps the strongest.
   - `utils/pain.py:wtp_score` counts spend-intent markers ("would pay", "$15/mo", "cancelled").
   - `utils/ranking.py:recency_bonus` decays exponentially (90-day half-life); needs a
     signal `created_at` (emitted by HN + GitHub; others get no bonus, never penalized).
   - `WTP_WEIGHT=2.0`, `RECENCY_MAX=5.0`, `RECENCY_HALFLIFE_DAYS=90`. (`agents/scout.py`)
5. **Deeper sources.**
   - **GitHub Issues** (`scrapers/github.py`) — developer-tool pain (budget-holding buyers).
     Works; ~90 signals/run. Optional `GITHUB_TOKEN` for higher rate limit.
   - **Trustpilot** (`scrapers/trustpilot.py`) — best-effort B2B/SaaS reviews. **Currently
     403-blocked (anti-bot)** but degrades gracefully (0 signals, never raises). Real SaaS
     review coverage would need a paid reviews API.
6. **LLM cluster-labeling.** `utils/labeler.py` — one batched LLM call distills the final
   selected signals into crisp one-line pain statements (prepended above the raw evidence),
   so the Validator scores the *problem*, not the noise. `CLUSTER_LABELING=true`.
7. **Category pain synthesis (app/play + GitHub)** (added 2026-06-09). `agents/category_pain.py`
   groups signals by category and runs **one LLM call per category** to extract the 2-3 pains
   that recur **across multiple products** — a category GAP, not one product's bug —
   **replacing** the raw per-product signals with those stronger cross-product signals.
   - **App/Play:** scrapers tag each review with `category` + `app`, sample 8 apps/category
     (was 5); e.g. 109 reviews → 6 category gaps, each naming the apps that share it.
   - **GitHub** (extended 2026-06-09): the scraper is now **category-driven like the stores** —
     it searches devtool domains (`GITHUB_CATEGORY_TERMS`: ci/cd, auth, orm, api gateway,
     observability, feature flags…), sorts by **reactions** (how many people want it =
     validation, akin to ratings), tags each issue's **repo** as the cross-item axis, and caps
     issues/repo (`GITHUB_MAX_ISSUES_PER_REPO=3`) so one mega-repo can't dominate. Synthesis
     finds requests that recur across **different repos** = a cross-repo devtool gap (verified:
     "database orm" → gaps across prisma/efcore/drizzle; "feature flags" → 28 issues / 22 repos).
   - The cross-item axis is the signal's `app` field (an app name, or `owner/repo` for GitHub);
     the prompt uses the right noun per source ("app" vs "project"). Sources eligible:
     `appstore, playstore, github`. Degrades per category (raw passes through if `<
     CATEGORY_PAIN_MIN_APPS` products / `< CATEGORY_PAIN_MIN_REVIEWS` items, or the LLM fails).
   - Discussion-style sources (Reddit, HN, Product Hunt) are NOT category-synthesized — no
     "product" axis; cluster-labeling already distills their recurring themes.
   - *Caveat:* a loose 2-word GitHub category (e.g. "feature flags") can match off-topic repos;
     the `GITHUB_CATEGORY_TERMS` list can be tuned for precision. `CATEGORY_PAIN_SYNTHESIS=true`.

---

## 3. Bug fixes

- **App Store single-review crash** (`scrapers/appstore.py`): Apple's reviews RSS returns a
  single dict (not a list) when an app has exactly one review → `'str' object has no
  attribute 'get'` killed the *entire* App Store source. Now normalized to a list.
- **Gap-score popularity bias** — see §2.1 (log-scaled).
- **Novelty-rescue over-firing** — see §2.2 (threshold 3 → 7).
- **CLI argv overflow** — see §1 (prompt via stdin).

---

## 4. Pipeline decoupling — resumable, step-by-step (Part 1 of approved plan)

**Why:** `run_pipeline()` was one in-process handoff passing return values stage→stage.
A full run takes 15–40 min and kept getting killed before Pass 2; recovery meant
hand-crafting id lists. **Now every stage reads its pending work from the DB.**

- **DB-driven, idempotent entrypoints** (optional arg; `None` ⇒ query the DB via a
  NULL-safe correlated `~exists()` "child does not exist"):
  - `swot_researcher.run(None)` → passing `ValidatedIdea` with no `SwotResearch`, top-N by
    score, capped at `MAX_SWOT_PER_RUN`.
  - `swot_synthesizer.run(None)` → complete/partial `SwotResearch` with no `SwotAnalysis`.
  - `synthesizer.run(None)` → PROCEED/CAUTION `SwotAnalysis` with no `Idea`.
- **`run_pipeline()` is now resumable** — calls the DB-driven stages in sequence; re-running
  `--now` after a kill skips completed work. Still reports only *this run's* analyses
  (so no Telegram re-spam of old ideas).
- **New CLI** (see §0): coarse `--stage idea|swot`, fine `--scout/--validate/--research/
  --synthesize/--ideate`, plus `--report` and `--status`. Each runs under the lockfile.
- **Cap-semantics note:** `MAX_SWOT_PER_RUN` (=5) now means "global unresearched backlog,
  top-N by score per run" (was "this validator-run's top-N"). Re-run `--research` to drain
  the backlog 5 at a time. There are currently **51 passing-but-unresearched ideas** queued.

---

## 5. Idea generation — stop the repeats (Part 2 of approved plan)

**Why:** of 24 generated ideas, the DB held **4 freelancer-invoicing apps** and **3
subscription trackers**, yet **0/24** were flagged similar.

Root causes & fixes (all in `agents/synthesizer.py`):
1. **Prompt was blind to existing ideas** → now shows the LLM the nearest existing concepts
   (`utils/deduplicator.py:top_similar`) and asks it to differentiate or pivot.
2. **Dedup threshold miscalibrated** — `is_duplicate()` reused `SIMILARITY_THRESHOLD=0.85`
   (for raw signals); real concept dups score 0.6–0.8. → new **`CONCEPT_SIMILARITY_THRESHOLD=0.6`**.
3. **Check was passive** → now **active**: on a duplicate it regenerates once
   (`CONCEPT_REGEN_MAX=1`) with a "change the wedge/audience/model" instruction.
4. **Richer context** → competitor names + `core_weakness` (`analysis.competitors`), 2–3
   low-star review complaints (`analysis.demand_data.prior_apps[*].reviews`), and SWOT prose
   are fed into the prompt so the concept attacks a specific gap vs named incumbents.
5. **Upstream pain-level dedup** → analyses targeting the same pain are collapsed to the
   highest-scoring one before generation (logs `pain-dup: skipping analysis X`).

**Verified live:** for the dog-walking pain it produced **PawPact** — a walker-accountability
*layer on top of* Rover/Wag! (named the incumbents, attacked the no-show gap, sidestepped the
"two-sided marketplace is capital-intensive" weakness). No longer a generic clone.

---

## 5b. Auto-pilot + Opportunity Judge (autonomous hunt) — added 2026-06-09

**Goal:** let the machine run on its own until it finds an idea worth proceeding with,
judged by a single score.

- **Opportunity Judge** (`agents/opportunity.py`): an LLM scorer that reads a finished
  idea's full dossier (pain, SWOT verdict/scores, demand, competitors, the concept) and
  returns a **0–100 opportunity score** on a fixed rubric — pain_intensity (20) + market_gap
  (20) + real_demand (20) + buildability (15) + monetizability (15) + wedge (10) — plus a
  **recommendation: PROCEED / ITERATE / DROP**, sub-scores, fatal-flaw, and reasoning. Persisted
  on the `Idea` row (`opportunity_score/_recommendation/_scores/_reasoning`, schema-migrated).
  `opportunity.run(ids=None)` scores given ideas (or all unscored).
- **`run.py --autopilot [N]`**: loops `scout → validate → research → synthesize → ideate →
  judge`, **up to N rounds** (`AUTOPILOT_MAX_ROUNDS=5`). Each round uses fresh feedback seeds
  (new categories every loop). **Stops** at the first idea scoring **≥ `AUTOPILOT_PROCEED_SCORE`
  (70) AND recommendation == PROCEED**; otherwise runs all N rounds and reports the **best
  found**. Runs under the lockfile; resilient (a round error is logged and the loop continues).
- **Verified:** judge scored 3 real ideas conservatively — MCPScope 72/ITERATE ("crowded
  field"), ReviewShield 62/ITERATE ("thin wedge"), AIFuse 61/ITERATE ("window closing"). No
  false PROCEED. (A full multi-round `--autopilot` run is expensive — not yet run end-to-end;
  every stage it calls is independently verified.)
- **Cost note:** each round is a full pipeline pass + one judge call per new idea; with the
  per-category LLM calls (§2.7) a round can be slow. Bounded by N rounds.

## 5c. Performance + visibility + actionability — added 2026-06-09

- **Concurrent LLM calls** (`utils/concurrency.py:pmap`). Independent `claude -p` calls now
  run through a bounded thread pool (`LLM_CONCURRENCY=4`): **validator** per-signal,
  **category-pain** per-category, **opportunity judge** per-idea. Pattern = read + LLM
  concurrently, **write sequentially** on the main thread. SQLite is put in **WAL mode +
  30s busy_timeout** (`db/models.py`) so concurrent sessions don't hit "database is locked".
  **Measured 3.6× faster** (4 judge calls: 51s → 14s) and the controlled concurrency avoids
  the flaky "exited 1" seen under rapid *sequential* CLI calls. Set `LLM_CONCURRENCY=1` to disable.
- **Funnel analytics** (`run.py --funnel`). Read-only view of where ideas die: raw→validated→
  passed-gate→researched→verdict (PROCEED/CAUTION/KILL, incl. demand-gate kills)→concept→
  opportunity rec→cleared-bar. *First run revealed* 0 PROCEED verdicts ever — so
  `SWOT_PROCEED_THRESHOLD` was **lowered 75→70** (and `AUTOPILOT_PROCEED_SCORE` 75→70, coupled
  to the judge's PROCEED rule) so genuinely strong ideas can reach PROCEED and the hunt can
  win. Demand gate still rarely fires (demand data usually unavailable). Use `--funnel` to keep
  tuning.
- **Cross-run pain memory** (`utils/pain_memory.py`, `PAIN_MEMORY=true`). Before writing new
  signals, Scout embeds each (crisp labeled) pain against **all past `ValidatedIdea` pain
  titles** and drops ones above `PAIN_MEMORY_THRESHOLD=0.72` cosine — so every run explores
  new ground instead of re-scoring known pains. No new storage (memory = the validated-idea
  history). Verified: drops rephrased known pains, keeps novel ones.
- **Build-readiness brief** (`agents/brief.py`, `run.py --brief [ID]`). One LLM call turns a
  winning idea into a concrete MVP plan — scope, first features (build order), tech stack,
  ≤8-week milestones, the wedge, landing-page copy, first-10-users, and de-risking. Persisted
  on `Idea.build_brief` and rendered to `reports/brief_<id>_<name>.md`. Defaults to the
  highest-opportunity idea. Verified live (TrialGuard → full Next.js/Vercel/Gmail-API plan).

## 5d. SWOT quality upgrades — added 2026-06-09

The two-pass SWOT (Pass 1 research → Pass 2 synthesis) got four upgrades to make the
proceed/kill decision sharper, plus a prompt-size fix that was needed to land them.

- **Adversarial second opinion** (`swot_synthesizer._challenge`, `SWOT_ADVERSARIAL=true`).
  After synthesis, a separate red-team LLM call argues the strongest case to KILL and names
  the single most-likely fatal flaw; `_apply_challenge` then **downgrades only** (PROCEED→
  CAUTION→KILL, never up). Persisted on `SwotAnalysis.challenge`. *Verified:* the onboarding
  idea was downgraded to **KILL** because the red-team flagged a fatal flaw — "no distribution
  path for a solo founder to reach HR/L&D buyers" — that the synthesis under-weighted.
- **LLM-tailored research queries** (`swot_researcher._plan_queries`, `SWOT_PLAN_QUERIES=true`).
  Pass 1 asks the LLM for sharp, idea-specific Google queries per quadrant instead of templated
  `pain + suffix` strings (falls back to templates). *Verified:* generated e.g. "WalkMe Pendo
  Appcues Intercom onboarding comparison" vs the old generic "{pain} alternatives".
- **Real competitor research** (Pass 1 competitor query group → `market_raw.competitors_search`;
  synthesizer `COMPETITORS_RAW` block + sourcing rule). Web/GitHub competitors, not just
  app-store prior-art — fixes the app-store bias for B2B/devtools. *Verified:* named **Pendo,
  Appcues, WalkMe** (real SaaS incumbents) with web source URLs.
- **Confidence-weighted scoring** (`swot_synthesizer._shrink`). The per-quadrant confidence the
  LLM already emits now shrinks each quadrant score toward the neutral 50 (`SWOT_CONFIDENCE_
  SHRINK={high:1.0,med:0.7,low:0.4}`), so a low-evidence "benign threats" can't dominate the
  0.35 weight. Unit-tested.
- **Prompt-size fix (required to land the above).** The synthesis prompt was dumping raw Serper
  JSON for every quadrant **and the full demand object (8 apps × 20 reviews) twice** — it blew
  past the 180s CLI timeout on mega-categories (e.g. "project management"). Added
  `_compact_search` (terse `title: snippet (link)`) for all evidence bundles and capped
  `_format_prior_attempts` (≤6 apps × 5 reviews). Worst-case prompt **56K → 25K chars**;
  synthesis now completes reliably.

## 5e. Pluggable web search (Serper / Brave) — added 2026-06-09

All web search now goes through **`utils/search.py:web_search(query, num)`** →
uniform `[{title, link, snippet}]`. Backend by `SEARCH_BACKEND`:
- **`auto`** (default): Serper if `SERPER_API_KEY` set, else **Brave** (the free option).
- **`serper`**: Google via Serper (free tier caps num=10/page → `web_search` paginates to `num`).
- **`brave`**: Brave Search API, **free tier 2,000 queries/month** — get a key at
  https://brave.com/search/api/ and set `BRAVE_API_KEY`.

**Both call sites route through it:** `swot_researcher` (the heavy user — ~14–18 searches/idea
across the 6 quadrant groups) and `scrapers/reddit.py` (`site:reddit.com` discovery). So the
project can run **with no Serper key** — set `BRAVE_API_KEY` instead.
- **Where Serper was used:** SWOT Pass-1 evidence + Reddit discovery (nothing else).
- The Telegram/research key checks now accept **either** `SERPER_API_KEY` **or** `BRAVE_API_KEY`.
- Verified live on Serper (auto-selected). Brave path implemented to its documented API but not
  live-tested (no key on hand) — add `BRAVE_API_KEY` and set `SEARCH_BACKEND=brave` to use it.

## 6. Config knobs added (all env-overridable, in `config.py`)

| Knob | Default | Purpose |
|---|---|---|
| `LLM_BACKEND` | `auto` (set to `cli` in `.env`) | which LLM backend: auto/cli/openai |
| `PAIN_KEEP_THRESHOLD` | `7` | novelty-rescue pain floor for sub-threshold clusters |
| `GAP_MIN_AUDIENCE` / `GAP_RATING_CEILING` | `500` / `3.7` | gap-targeting "underserved" criteria |
| `FEEDBACK_SEEDS` / `_SEED_COUNT` / `_HISTORY_MAX` | `true` / `8` / `40` | adaptive app-store seeds |
| `WTP_WEIGHT` / `RECENCY_MAX` / `RECENCY_HALFLIFE_DAYS` | `2.0` / `5.0` / `90` | discovery ranking |
| `CLUSTER_LABELING` | `true` | LLM crisp-pain labeling of selected signals |
| `CATEGORY_PAIN_SYNTHESIS` | `true` | replace app/play reviews with cross-app category gaps |
| `CATEGORY_PAIN_MIN_REVIEWS` / `_MIN_APPS` / `_MAX_REVIEWS` | `6` / `2` / `30` | category-pain thresholds |
| `APPSTORE_APPS_PER_TERM` / `PLAYSTORE_APPS_PER_TERM` | `8` | apps sampled per category (was 5) |
| `SEARCH_BACKEND` / `BRAVE_API_KEY` | `auto` / `""` | web-search provider: auto→Serper if key else Brave; or `serper`/`brave` |
| `REDDIT_USE_SERPER` / `REDDIT_SEARCH_RESULTS` | `true` / `20` | Reddit via web search (`site:reddit.com`), results/subreddit |
| `GITHUB_CATEGORY_TERMS` | devtool domains | category-driven GitHub search (sorted by reactions) |
| `GITHUB_ISSUES_PER_CATEGORY` / `GITHUB_MAX_ISSUES_PER_REPO` | `30` / `3` | GitHub fetch depth + per-repo cap |
| `GITHUB_TOKEN` | `""` | optional, raises GitHub rate limit (works unauth) |
| `TRUSTPILOT_CATEGORIES` / `_PAGES_PER_CATEGORY` / `_MAX_RATING` | list / `1` / `3` | Trustpilot source |
| `CONCEPT_SIMILARITY_THRESHOLD` | `0.6` | concept/pain dedup bar (separate from 0.85 signal bar) |
| `CONCEPT_NEIGHBORS` | `5` | existing concepts shown to the LLM |
| `CONCEPT_REGEN_MAX` | `1` | regen attempts when a concept is a duplicate |
| `AUTOPILOT_MAX_ROUNDS` | `5` | max discovery rounds in `--autopilot` |
| `AUTOPILOT_PROCEED_SCORE` | `70` | opportunity-score bar to stop the hunt (+ PROCEED rec); judge's PROCEED rule references it |
| `SWOT_PROCEED_THRESHOLD` | `70` | overall_score for a PROCEED verdict (was 75) |
| `LLM_CONCURRENCY` | `4` | concurrent `claude -p` calls (validator/category-pain/judge); 1 = off |
| `PAIN_MEMORY` / `PAIN_MEMORY_THRESHOLD` | `true` / `0.72` | drop already-evaluated pains across runs |
| `SWOT_ADVERSARIAL` | `true` | red-team second opinion (downgrade-only) on the verdict |
| `SWOT_PLAN_QUERIES` | `true` | LLM-tailored Pass-1 research queries (vs templates) |
| `SWOT_CONFIDENCE_SHRINK` | `{high:1.0,med:0.7,low:0.4}` | shrink low-confidence quadrants toward 50 |

---

## 7. Files touched this session

**New:** `agents/seed_planner.py`, `agents/category_pain.py`, `agents/opportunity.py`,
`agents/brief.py`, `scrapers/github.py`, `scrapers/trustpilot.py`, `utils/pain.py`,
`utils/ranking.py`, `utils/labeler.py`, `utils/concurrency.py`, `utils/pain_memory.py`, `utils/search.py`,
`README.md`, `backlog.md` (this file), `pytest.ini`, `requirements-dev.txt`,
`tests/` (conftest + 7 test modules, incl. `test_swot_scoring.py`).

**Modified:** `config.py`, `run.py`, `db/models.py`, `agents/scout.py`,
`agents/swot_researcher.py`, `agents/swot_synthesizer.py`, `agents/synthesizer.py`,
`scrapers/reddit.py`, `scrapers/appstore.py`, `scrapers/playstore.py`,
`scrapers/hackernews.py`, `utils/claude_caller.py`, `utils/deduplicator.py`.

**⚠️ All of the above is UNCOMMITTED** (working tree only). Last commit is `7dc3914`.
`.env` is gitignored — never commit it (holds the LLM key, mask as `<redacted>` if shown).

---

## 7b. Tests (added 2026-06-09)

First test suite — **pytest, Core + DB scope, 44 tests, ~0.3s, no LLM/network.**

```bash
.venv/bin/python -m pip install -r requirements-dev.txt   # one-time (installs pytest)
.venv/bin/python -m pytest                                # run all
```

- `tests/test_pain.py` — `pain_score`, `wtp_score` (markers, caps, empties).
- `tests/test_ranking.py` — `recency_bonus` decay (fresh=max, half-life=½), `_to_dt`, `discovery_score`.
- `tests/test_gap_score.py` — App/Play `_gap_score` **log-scaling regression guard** (failing
  incumbent must outrank beloved leader), audience floor, `_is_underserved`, install/avg parsing.
- `tests/test_text_utils.py` — `content_hash` determinism + 200-char prefix, Reddit `_clean_title`.
- `tests/test_synthesizer_logic.py` — context-block builders + `_dedup_by_pain` (embeddings stubbed).
- `tests/test_db_logic.py` — temp SQLite: migration idempotency, `pending_counts()` `~exists`
  queries, resumable research selection (passing+unresearched, capped, score-ordered).
- Fixture `tests/conftest.py:temp_db` points the ORM at a throwaway SQLite file.
- Refactor for testability: `run.py` gained `pending_counts()` (the `~exists` queries `status()` prints).
- **Not covered yet (Tier 3):** agent flows with `call_json`/`requests` mocked (validator,
  synthesizer regen loop, opportunity judge, category-pain) — see §9.

## 8. Known issues / caveats

- **Claude CLI is slow + flaky on rapid sequential calls.** Use the step-by-step stages;
  a single stuck idea can burn ~9 min (3 retries × 180s). Reliability is much better after
  the stdin fix, but batch Pass 2 over 5 ideas can still take a while.
- **Trustpilot is 403-blocked** — kept as a zero-cost best-effort source; yields nothing for now.
- **`pytrends` (Google Trends) is frequently 429 rate-limited** — demand's trend component
  degrades to "unavailable"; volume from app/play store still counts.
- **No `OPENROUTER_API_KEY`** set → no LLM fallback if the CLI fails on a call.
- **Reddit access (resolved 2026-06-09): now via Serper/Google.** Reddit **disabled
  self-service API app creation** (`prefs/apps` fails) AND now **403s the no-auth `.json`
  endpoints**. The `.rss` feed still works but is thin (capped, HTML-truncated, no real
  crawl, ~334 low-quality signals). **Fix:** `scrapers/reddit.py` now searches Reddit via
  **Serper** (`site:reddit.com/r/<sub>`, the key we already pay for) — Google indexes Reddit
  deeply, so this returns relevance-ranked, pain-dense threads (~180/run, far better
  targeted). Method priority: PRAW (dormant) → **Serper** → RSS fallback. **Serper free tier
  caps `num=10`** per call (num>10 → 400), so we paginate (`REDDIT_SERPER_PAGES=3`, num=10
  each). Titles are cleaned of Google "… - Reddit" / "r/X on Reddit:" decorations. **Risk:**
  if Google de-indexes or Serper credits run out, it auto-falls-back to thin RSS.

---

## 9. Pending / not yet done

- [ ] Live full `--stage idea` → `--stage swot` cycle end-to-end (logic verified; not run start-to-finish).
- [ ] Drain the **51 unresearched** passing ideas (run `--research` repeatedly, 5/run).
- [ ] Decide whether to **commit** this session's work (currently all uncommitted).
- [ ] Optional: Tier-3 tests — mock `call_json`/`requests` to cover agent flows (validator,
  synthesizer regen loop, opportunity judge, category-pain synthesis).
- [ ] Optional: paid B2B-reviews API if real G2/Capterra/Trustpilot coverage is wanted.
- [x] ~~Optional: Reddit OAuth creds for richer Reddit pain~~ — **not feasible** (Reddit
  disabled self-serve app creation). **Solved a better way:** Reddit now searched via
  Serper/Google (`site:reddit.com`), richer than RSS — see §8.
- [ ] Optional future: persist a `selected_for_swot` flag on `ValidatedIdea` (not needed now).

---

## 10. Current DB state (as of last `--status`)

- pending signals (→ `--validate`): **0**
- passed, unresearched (→ `--research`): **51**
- research, unsynthesized (→ `--synthesize`): **3**
- analyses, unideated (→ `--ideate`): **3**
- Generated ideas so far: ~24 (the duplicate-heavy batch that motivated §5).

---

## 11. MCPScope build hand-off (2026-06-10)

- Decision: **CONDITIONAL GO** — Phase 2 (4-week MVP) active; Gate W1 = day-7 abort
  check. See `reports/action_plan_mcpscope.md`.
- **`reports/mcpscope_build_plan.md`** = self-contained implementation plan, written to
  be copied into a NEW repo as `PLAN.md` and executed by a fresh Claude instance
  (wedge invariants, schema, week-by-week tasks + acceptance criteria, Gate W1 inline).
  The build happens OUTSIDE this repo; this repo stays the idea machine + validation log.

---

## 12. Ecosystem-wave scout — discovery beyond pain mining (2026-06-11)

**Why:** funnel audit showed pain mining finds *real* pains that SWOT correctly
kills for structural reasons (59 KILL / 27 CAUTION / 0 PROCEED at SWOT level;
kill reasons ≈ "pain real BUT hyper-competitive / users won't pay / no
distribution"). 58% of signals came from consumer app stores → 0 winners. The
single winner (MCPScope, judge 72 PROCEED) was a different archetype: an
*emerging-ecosystem tooling gap*, found by accident via one HN post.

**What:** `scrapers/ecosystem.py` generates that archetype on purpose
(demand-first, "picks & shovels"):
1. **Wave detection** — GitHub repo search (free): repos < `ECOSYSTEM_MAX_AGE_DAYS`
   (540) with ≥ `ECOSYSTEM_MIN_STARS` (800), ranked by star **velocity**
   (stars/day).
2. **Platform filter** — one LLM call keeps platform-shaped repos (things devs
   build ON); keyword heuristic fallback if the LLM fails.
3. **Gap probe + synthesis** — per top wave (`ECOSYSTEM_TOP_WAVES`=3), GitHub
   search per `ECOSYSTEM_GAP_TERMS` category (debugger/testing/monitoring/
   registry/analytics/deploy/security/migration); `classify_gap`: <5 repos OR
   strongest < `ECOSYSTEM_GAP_SATURATED_STARS` (300) ⇒ unserved. One batched
   LLM call writes pain-style signals citing the growth evidence.

**Wiring:** registered as source `"ecosystem"` in `agents/scout.py:_SCRAPERS`
(runs in every default scout). Signals carry `synthesized: True`; `_cluster()`
now keeps synthesized singletons (their cross-mention evidence lives upstream —
the cluster-size gate doesn't apply). Not touched by category-pain synthesis
(source not in its `_UNIT` map). Throttles GitHub search 6.5s/req unauth,
0.5s with `GITHUB_TOKEN`. Never raises; every phase degrades to `[]`/heuristic.

**Tests:** `tests/test_ecosystem.py` — 17 offline tests (velocity ranking, gap
classification, short-name resolution, LLM-failure fallbacks, end-to-end scrape
with mocked network+LLM, scout cluster-gate bypass). Suite: **61 passed**.

**Audit follow-ups not yet built** (next levers, in recommended order):
money-flow mining (Upwork/Gumroad/template marketplaces — attacks the #1 kill
reason), kill-reason feedback into scout ranking, source rebalance away from
consumer stores, trend-velocity scoring from pain-memory history.
