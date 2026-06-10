# MCPScope — Phase 1 Execution Plan: Validate Before Building

*Drafted 2026-06-10. Detail for Phase 1 of [`action_plan_mcpscope.md`](./action_plan_mcpscope.md).*
**Budget: ~2-4 days, $0. Output: a filled-in Gate G0 scorecard and a build / no-build decision.**

> **Helper scripts: [`../validation_mcpscope/`](../validation_mcpscope/README.md)** —
> automates the Day-1 competitor sweep (`competitor_sweep.py` → `competitor_sweep.md`),
> the Day-3 target list (`find_outreach_targets.py` → `outreach_targets.md`), and ships
> the deployable landing page (`landing/index.html`).
> **First findings (2026-06-10):** `mcpscope` is **TAKEN on PyPI** (free on npm/GitHub —
> pick a new pip name or pivot install story) and **MCPJam/inspector (⭐2k)** is a direct
> competitor the SWOT missed — audit it alongside the official Inspector on Day 1.

**Goal:** prove (or disprove) two assumptions before writing any proxy code:
1. The free official MCP Inspector leaves real, nameable gaps.
2. Developers feel the debugging pain strongly enough to sign up for a fix.

**Anti-goals:** do NOT start the proxy. Do NOT announce "I'm building X" before the
audit (you may discover the Inspector already covers it). Ask about the *pain* first,
pitch second.

---

## Day 1 (morning) — Competitor audit: the official MCP Inspector

Install and genuinely use it against a real server you already run:

```bash
npx @modelcontextprotocol/inspector <your-mcp-server-command>
```

Fill in this gap checklist (✅ Inspector does it / ❌ gap MCPScope fills):

| Capability | Inspector | Notes |
|---|---|---|
| Interactively test a server's tools by hand | | expected ✅ |
| **Passively watch a LIVE agent session** (Claude Desktop mid-conversation) | | expected ❌ — core wedge |
| Persistent call **history** across sessions (SQLite) | | |
| **Search/filter** across thousands of calls | | |
| **Diff** payloads between calls | | |
| **Replay** a captured call / **stub** offline | | |
| Latency / error / timeout stats per tool | | |
| Works with zero changes to the agent's config | | |

Also skim 30 min for other direct tools (GitHub search: `mcp proxy`, `mcp inspector`,
`mcp traffic`, npm + PyPI). Log anything found in the scorecard.

**Decision rule:** need **≥4 hard ❌ gaps** including "passively watch a live agent
session." Fewer → the wedge is too thin; stop here and report back.

## Day 1 (afternoon) — Landing page + waitlist

Stack: Cloudflare Pages (free) + any form/email capture (Tally / Formspree / Buttondown
— pick the one you already have). Single page, no product screenshots needed yet — a
terminal mockup or asciinema-style text block is enough.

Copy (from the brief, ready to paste):

> # Charles Proxy for your AI tool calls
> MCPScope intercepts every MCP tool invocation locally — watch your agent's calls
> live, inspect payloads, replay bugs offline. Free, open source, nothing leaves
> your machine.
>
> `pip install mcpscope` — coming soon. **[Get notified at launch →]**

Below the fold, three bullets (the gaps confirmed in the audit this morning), e.g.:
- See every tool call your agent makes, live, with latency and errors
- Full session history you can search, filter, and diff
- Replay any call to reproduce a bug — even offline

Add the simplest analytics (Cloudflare Web Analytics, free) so you can tell visits
from signups.

## Day 2 — Community pain survey (ask, don't pitch)

Post a genuine question — pain first, no product link in the post itself:

**Where:** Anthropic MCP Discord (`#mcp-dev`), Model Context Protocol GitHub
Discussions, r/ClaudeAI or r/LocalLLaMA (one, not both).

**Draft post:**

> **How do you all debug MCP tool calls?**
> When my agent misbehaves I end up sprinkling print statements into the server or
> tailing logs, and I still can't see what the client actually sent. The official
> Inspector is great for poking a server by hand, but I haven't found a way to watch
> a *live* session (e.g. Claude Desktop mid-conversation).
> What's your workflow? Is this just me?

Reply to every response. Only share the landing page when someone expresses the pain
("I'd use a proxy for this") — then it's helpful, not spam.

**Capture in the scorecard:** number of replies, how many describe the same pain,
how many name an existing fix you didn't know, exact quotes (future marketing copy).

## Day 3 — Direct outreach (n=5-10)

Find people with demonstrated pain, freshest first:
- GitHub: issues mentioning `debugging`/`logging`/`tracing` in popular MCP server
  repos (`mcp-server-filesystem`, `mcp-server-git`, community servers).
- X/Twitter + Discord search: "MCP debugging", "MCP tool call", last 30-60 days.

**DM/comment template (personalize the first line):**

> Saw your issue about [their specific problem]. I'm exploring a local-first proxy
> that records every MCP tool call (live feed, history, replay) — no cloud, no
> account. Would that have helped in your case? Genuinely asking before I build it.

Log every reply verbatim. A "meh" is as valuable as a "yes."

## Day 3-4 — Score Gate G0 and decide

Fill in the scorecard (keep it in this file):

| Signal | Threshold | Actual | Pass? |
|---|---|---|---|
| Inspector gap count (hard ❌) | ≥4, incl. live-session watch | | |
| Waitlist signups | ≥25 | | |
| Survey replies describing the pain | ≥5 distinct people | | |
| Outreach: "yes that would have helped" | ≥3 of 5-10 | | |
| Unknown competitor that already nails it | none found | | |

**Decision:**
- **Pass (≥3 of 5 rows, incl. the gap row):** → Phase 2. Day 1 of the build is the
  stdio proxy core; the audit notes become the v0.1 feature cut.
- **Borderline:** extend 3 more days — post the demo *concept* (mock GIF) to Show HN
  as "Ask HN: would you use this?" before deciding.
- **Fail:** don't build. Write the post-mortem in this file (which assumption died),
  feed "mcp inspector/proxy/observability" into the idea machine's pain memory as
  evaluated, and run a fresh discovery cycle (`run.py --autopilot`).

## Distribution playbook (how the page actually gets traffic, $0)

Priority order — all organic, all places MCP devs already are. Paid ads are
deliberately OUT (wrong audience quality for devtools, pollutes the G0 signal).

| # | Channel | What | When |
|---|---|---|---|
| 1 | **Direct outreach** (highest signal) | The 25 GitHub-issue authors in `outreach_targets.md` + the authors of [inspector#1438](https://github.com/modelcontextprotocol/inspector/issues/1438) (asked for replay) and [#1417](https://github.com/modelcontextprotocol/inspector/issues/1417) (asked for persist/search) — they literally requested MCPScope features | Day 3 |
| 2 | **Anthropic MCP Discord** `#mcp-dev` | Pain-first survey post (draft above); link only in replies | Day 2 |
| 3 | **MCP GitHub Discussions** | Same survey post | Day 2 |
| 4 | **Reddit** r/ClaudeAI *or* r/LocalLLaMA (one) | Same survey post | Day 2 |
| 5 | **X/Twitter** | Draft below; tag nothing, just ship it; reply to anyone tweeting MCP-debugging pain | Day 2-4 |
| 6 | **"Ask HN"** (only if G0 is borderline) | Draft below — concept validation, not a launch | Day 5+ |
| 7 | **Show HN + awesome-mcp list PRs + Product Hunt** | The REAL launch push — not now | Week 8, after the build |

**X/Twitter draft:**

> Debugging MCP tool calls today = sprinkling print statements into your server and
> praying. The official Inspector is great for poking a server by hand — but nothing
> lets you watch a LIVE agent session.
> I'm building a local-first proxy that records every call: live feed, history, replay.
> Free, open source, nothing leaves your machine. Waitlist: <URL>

**Ask HN draft (borderline-G0 fallback):**

> **Ask HN: Would you use a Charles Proxy for MCP/AI tool calls?**
> When my agent misbehaves I can't see what the client actually sent — the official
> MCP Inspector tests servers by hand but can't observe a live session, and its
> history dies on reload (verified). I'm considering a pip-installable local proxy:
> live TUI feed, SQLite history you can search/diff, offline replay. Free + OSS.
> Would this help your workflow, or is print-debugging good enough?

**Rules that keep the signal clean:** pain first, pitch second (link only in replies
to people who express the pain); personalize every DM; one community post per channel
— no spray. The G0 number only means something if the traffic was genuinely interested
developers, not karma tourists.

## Time & cost summary

| Item | Time | Cost |
|---|---|---|
| Inspector audit + competitor sweep | 3-4 h | $0 |
| Landing page + waitlist + analytics | 3-4 h | $0 (free tiers) |
| Community post + replies | 1-2 h spread over 2 days | $0 |
| Direct outreach (5-10 people) | 2 h | $0 |
| Scoring + decision | 1 h | $0 |
| **Total** | **~1.5-2 focused days spread over 4** | **$0** |
