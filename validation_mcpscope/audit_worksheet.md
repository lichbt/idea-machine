# Day-1 Audit Worksheet — Official Inspector & MCPJam vs the MCPScope wedge

*Docs-level pre-audit done 2026-06-10 (READMEs fetched & analyzed). Your job: ~45 min
hands-on to verify the rows marked ⚠️verify, then fill the verdict. Part of
[`../reports/action_plan_mcpscope_phase1.md`](../reports/action_plan_mcpscope_phase1.md).*

## Pre-filled gap checklist (docs level)

| Capability | Official Inspector | MCPJam | MCPScope wedge? |
|---|---|---|---|
| Interactively test a server's tools by hand | ✅ (its core purpose) | ✅ (+ LLM chat playground, evals, OAuth tests) | — |
| **Passively watch a LIVE agent session** (Claude Desktop mid-conversation, no config surgery) | ❌ — it *is* the client; "proxy" = bridge from its own web UI to the server | ❌ — active platform; you connect servers *to it* | **✅ core wedge** ⚠️verify |
| Persistent call **history** across sessions | ❌ not documented (session-scoped request history only) | ❌ not documented | ✅ ⚠️verify |
| **Search/filter** across thousands of calls | ❌ not documented | ❌ not documented | ✅ ⚠️verify |
| **Diff** payloads between calls | ❌ | ❌ | ✅ |
| **Replay** a captured call / **stub** offline | ❌ | ❌ | ✅ |
| Latency/error/timeout stats per tool | ⚠️ partial (timeouts, per-session errors) | ❌ (token usage in chat only) | ✅ |
| Zero changes to the agent's config | n/a (it replaces the agent) | n/a | ✅ |

**Docs-level count: ~6 hard gaps in BOTH tools, including the core live-session wedge →
G0's "≥4 gaps incl. live-watch" PASSES on paper.** Hands-on confirms docs match reality.

Notes from the docs:
- Official Inspector = React web UI + Node "proxy" — but that proxy bridges *its own UI*
  to a server; it cannot attach to an existing client↔server session. Explicitly dev-only
  ("should not be exposed to untrusted networks").
- MCPJam = Apache-2.0 testing/eval platform (hosted app, desktop, Docker, npx) with paid
  tiers. Closest overlap is its LLM-chat trace view — but that's *their* client's traffic,
  not your real agent's. Watch their evals/CI angle; they could move toward observability.

## Hands-on protocol (~45 min total)

**Setup (5 min)** — needs Node:
```bash
# a throwaway test server with sample tools (echo, add, longRunning...)
npx -y @modelcontextprotocol/server-everything
```

**A. Official Inspector (~15 min) — ✅ DONE hands-on 2026-06-10 (v0.22.0, driven via
browser automation against `server-everything` v2.0.0). All docs-level ❌ CONFIRMED:**
1. Ran `echo` 5×; History showed 8 numbered JSON-RPC entries (initialize, tools/list,
   5× tools/call).
2. Expanded entry shows **raw request/response only — no timestamp, no latency, no
   replay button, no diff**. History panel has **zero search inputs** (only "Clear").
3. **Persistence test: reload → disconnected, history WIPED ("No history yet")** —
   history is in-memory React state. ❌ confirmed.
4. **Wedge test: no attach-to-live-session mode anywhere** — the UI is Transport/
   Command/Arguments + Connect, i.e. the Inspector spawns/connects to the server as
   its own client. Nothing can observe an existing client↔server pair. ❌ confirmed.

**B. MCPJam — ✅ DONE hands-on 2026-06-10 (npx @mcpjam/inspector, driven via browser
automation against its bundled demo Excalidraw server):**
1. **Architecture: a playground/EMULATOR** — "This is your playground for MCP"; it
   emulates hosts/clients (Desktop, locale, timezone, permission modes, host
   capabilities) to test *your server*. No attach-to-live-agent mode anywhere.
   ❌ wedge confirmed. (Note: it squats port 6274, same as the official Inspector.)
2. **Trace view DOES show a per-call latency timeline** (e.g. "Tool · read_me — 60ms")
   — richer than the official Inspector, but only for its own playground session.
3. **Persistence: trace WIPED on reload** (anonymous/local). A "Shared Sessions"
   feature exists behind sign-in → their hosted tier is moving toward session
   sharing. **Watch item: MCPJam is the team-collab competitor to track.**
4. Search box is "Search tools..." (tool list only) — **no search over call history**.
   "Saved" = saved request presets (authoring aid, not replay of captured traffic).
   "Compare" compares host/client emulations, not historical payload diffs.

**C. Issue-tracker demand sweep — ✅ DONE (automated). Users are ASKING the official
Inspector for MCPScope features:**
- [#1438](https://github.com/modelcontextprotocol/inspector/issues/1438) — "History:
  make **Pin and Replay** work on HistoryEntry items"
- [#1417](https://github.com/modelcontextprotocol/inspector/issues/1417) — "**Persist**
  per-screen selection and **search/filter**"
- PRs in flight: SortToggle for History (#1372), persist per-screen state (#1420)
- MCPJam is adding a "snapshot History tab" ([#2526](https://github.com/MCPJam/inspector/pull/2526))

→ Double-edged: real demand evidence for history/persist/replay, AND both incumbents
are drifting toward *session-scoped* versions of those features. MCPScope's durable
differentiation is the part neither is building: **passively capturing a REAL agent's
live traffic, storing it across sessions locally, and replaying it.**

**⚠️ UPDATE (2026-06-10, evening):** during outreach we found BOTH issues already
CLOSED as completed — Inspector **shipped per-screen persistence (#1417) and History
Pin & REPLAY (#1438 → PR #1441, merged)** in the last week, under an active
**"Inspector V2 Working Group"** (met 2026-06-10). My npx audit caught released
v0.22.0; v2 is moving fast behind it. Consequences:
- The landing page's "history/search/diff/replay" cards will be PARTIALLY matched by
  Inspector V2 — *for the Inspector's own test session*. Cross-session storage was
  still an open question in #1438.
- The wedge claim must lead everything: **live capture of a REAL agent's traffic
  (Claude Desktop mid-conversation), stored across sessions** — still absent and
  architecturally out of scope for a connect-to-server tester.
- The action plan's "launch within 4 weeks" urgency is now confirmed, not theoretical.

## Verdict — filled 2026-06-10 (hands-on by automation; spot-check freely)

- Hard gaps confirmed in BOTH: **5 / 8** (live-attach, persistent history, history
  search, payload diff, replay-of-captured) — plus latency missing in the official one.
- Live-session wedge survives? **YES** — both are architecturally clients/emulators;
  neither can observe an existing agent↔server session.
- Surprises vs docs: MCPJam's trace has latency; both tools are actively adding
  session-history features (erodes secondary differentiators over time — ship fast).
- → **G0 gap row: PASS** ✅

Next: deploy the landing page + run the Day-2 survey (manual). The two strongest
landing-page claims, verified: "watch a live agent session" and "history that
survives a restart".

## MCPJam deep-estimate + market sizing (2026-06-10, API data)

| Metric | Official Inspector | MCPJam |
|---|---|---|
| npm downloads / month | **891,237** | 16,305 |
| GitHub stars (age) | 10,042 (20 mo) | 2,007 (12.5 mo) |
| Commit velocity (30d) | active (V2 WG) | **100+ commits** (funded-team pace) |
| Building the live-attach wedge? | ❌ (architecture + V2 scope) | ❌ (zero issues/PRs mention proxy/observe/live traffic) |

- **Market size, directly measured:** ~890K monthly installs of the category-defining
  inspection tool = a large, real, growing dev pool. MCPJam at 16K/mo proves a second
  tool can coexist.
- **Threat read:** both incumbents are fast but BOTH are heads-down on the
  test-harness paradigm; neither has the wedge on any public roadmap.
- **G0 competitive rows: decisively PASSED.** Demand rows (signups/replies) pending —
  treated as a week-1 build checkpoint per the conditional-GO decision.
