# MCPScope — Action Plan

*Drafted 2026-06-10. Companion to [`brief_22_MCPScope.md`](./brief_22_MCPScope.md).
Idea source: Product Idea Machine — Opportunity Judge 72/100 PROCEED (only idea of 86
analyses to clear the bar).*

> **STATUS (2026-06-10): CONDITIONAL GO — Phase 2 build starts now.**
> G0's competitive/market rows passed decisively the same day (audit + MCPJam
> deep-estimate + 891K/mo measured market); the demand rows physically need days to
> accumulate, so they moved to **Gate W1** (a day-7 checkpoint with hard abort
> criteria) instead of blocking the start. Rationale: Inspector V2 ships weekly —
> waiting 4 idle days costs ~15% of the launch window, while week-1 code (the proxy
> core) is cheap and useful even on abort.

**One-liner:** Charles Proxy for AI tool calls — a local-first MCP traffic inspector.
**Strategic posture:** the basic proxy is a commodity (weekend-buildable, free official
MCP Inspector exists). Therefore: **ship fast, win the indie crowd with the free local
tool, monetize the team/security/prod layer that a bundled single-user inspector will
never prioritize.** Speed and distribution are the moat, not tech.

---

## Phase 1 — Validate cheaply ✅ EXECUTED 2026-06-10 (results in [`../validation_mcpscope/audit_worksheet.md`](../validation_mcpscope/audit_worksheet.md))

- [x] **Audit official Inspector + MCPJam** — hands-on, automated browser. **5/8 hard
      gaps in both, incl. the live-attach wedge.** Intel: Inspector V2 WG shipped
      session persistence + Pin/Replay the same week (session-scoped only).
- [x] **Survey posted** — MCP Discussions [#2899](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/2899)
      + `#inspector-dev` V2 roadmap probe (the wedge question, asked to the
      maintainers directly).
- [x] **Landing page + waitlist live** — https://mcpscope.pages.dev, Formspree wired
      and test-verified; copy sharpened to wedge-only claims.
- [x] **MCPJam deep-estimate** — 16K npm dl/mo vs official's **891K/mo** (market size,
      directly measured); 100+ commits/30d but **zero roadmap signals toward the
      wedge**. No unknown competitor nails it.
- [x] **Gate G0 → CONDITIONAL PASS:** competitive + market rows passed outright;
      demand rows (signups ≥25 / replies ≥5 / outreach ≥3) deferred to Gate W1.

## Phase 2 — Build the MVP (Weeks 1-4, compressed from the brief's 8) ← WE ARE HERE

The adversarial SWOT's top risk is Anthropic shipping a first-party inspector — so
launch in 4 weeks with a smaller cut, not 8 with everything.

**Gate W1 (day 7 of the build) — the deferred demand check. Hard abort criteria,
written now while objective:**
- ABORT if the `#inspector-dev` answer is "V2 will do passive observation," OR
- ABORT if signups ≈ 0 AND both community posts got zero resonance by day 7.
- Otherwise: continue to week 2. (Replies/signups also feed week-4 launch copy.)
- On abort: keep the proxy core as OSS scratch, feed findings to pain memory, resume
  discovery (`run.py --autopilot`).

- [ ] **Wk 1 — Proxy core:** stdio transport wrapper (subprocess stdin/stdout splice)
      teeing JSON-RPC frames to SQLite (sessions, calls, payloads). Build against the
      typed **MCP Python SDK** (protocol-churn insurance). Verify end-to-end with
      Claude Desktop + one real MCP server. **Also wk 1: settle the package name**
      (`mcpscope` is TAKEN on PyPI; free on npm/GitHub) — pick pip-installable name +
      matching domain in one decision, update the landing page.
- [ ] **Wk 2 — SSE transport + CLI:** `mcpscope run --stdio <cmd>` / `--sse <url>`,
      pytest fixtures for both transports.
- [ ] **Wk 3 — Textual TUI:** live call feed (tool, status, latency), detail pane with
      JSON pretty-print, single-keystroke filter. Works in tmux + VS Code terminal.
- [ ] **Wk 4 — Packaging + demo:** clean `pip install mcpscope`, auto-detect
      claude-desktop config, README with 3 copy-paste quickstarts, 90-second demo GIF.
- **Deferred to v0.2 (post-launch):** replay/stub/export, payload diff. They're the
      brief's weeks 4-5; cut them to hit the 4-week launch window.
- **Stack:** Python 3.11 asyncio + Textual + aiosqlite + Typer + httpx. Infra cost: $0
      (everything runs on the user's machine).

## Phase 3 — Launch + listen (Weeks 5-6)

- [ ] **Show HN** with the demo GIF (day of first solid build).
- [ ] Anthropic MCP Discord `#mcp-dev`, MCP GitHub Discussions, r/LocalLLaMA.
- [ ] Reply to open `debugging`-tagged issues in popular MCP server repos; DM ~5 devs
      who tweeted MCP-debugging pain recently.
- [ ] Instrument the **north-star metric: weekly active proxied sessions** (opt-in
      anonymous ping) — not signups, not stars.
- [ ] Ship v0.2 within 2 weeks of launch from real friction feedback (replay/diff).
- [ ] **Gate G1 (end of week 8):** WAPS growing week-over-week AND ≥3 unsolicited
      "can my team share these sessions?"-type requests.
      *Pass → Phase 4. Stall → keep it as a free OSS calling card; return the idea
      machine to discovery.*

## Phase 4 — Monetize the layer DIY won't reach (Months 3-6)

Never charge for basic inspection (commodity + free official tool). Charge for:

1. **Team tier ~$49/mo flat** — cloud session sync, shared/annotated sessions,
   retention, team dashboard. Build only after G1 demand signals.
2. **Later, security/governance tier** — secret/PII redaction, tool allow-listing,
   audit logs, SSO. This is the durable enterprise money and the true moat.
- **Infra (Cloudflare Workers + R2 + D1):** ~$15-50/mo at ~100 teams → ~99% gross
  margin. Cost disciplines from day one: **batch session writes** (never per-call),
  truncate/compress large payloads, tiered retention (hot 7d → cold).
- [ ] **Gate G2:** 10 paying teams (~$500 MRR) within 8 weeks of the paid tier.
      *Pass → double down. Fail → the free tool stays as reputation/distribution.*

## Standing risk watch (review weekly)

| Risk | Mitigation |
|---|---|
| Anthropic bundles a real inspector into Claude Desktop | Launch in 4 wks; own team/governance features a single-user tool won't do |
| MCP protocol churn breaks the proxy | Typed SDK for parsing; watch spec releases; 24h patch SLA |
| Basic proxy is weekend-cloneable | Compete on polish + maintenance + distribution speed, monetize only the cloud layer |
| Tiny market today | Cost base ≈ $0, so patience is cheap; judge by WAPS growth, not absolutes |

## Kill criteria (written while objective; G0 superseded by Gate W1)

- **Gate W1 fails** (day 7: maintainers confirm V2 passive observation, or zero
  resonance + zero signups) → stop; keep proxy core as OSS scratch; resume discovery.
- 8 weeks post-launch: WAPS flat AND no team-feature pull → freeze as free OSS.
- Anthropic ships a first-party inspector covering **live proxying of real agents** +
  cross-session history *before* MCPScope has a user base → pivot straight to
  governance/prod or stop.
