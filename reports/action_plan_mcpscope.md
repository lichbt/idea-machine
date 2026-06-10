# MCPScope — Action Plan

*Drafted 2026-06-10. Companion to [`brief_22_MCPScope.md`](./brief_22_MCPScope.md).
Idea source: Product Idea Machine — Opportunity Judge 72/100 PROCEED (only idea of 86
analyses to clear the bar).*

**One-liner:** Charles Proxy for AI tool calls — a local-first MCP traffic inspector.
**Strategic posture:** the basic proxy is a commodity (weekend-buildable, free official
MCP Inspector exists). Therefore: **ship fast, win the indie crowd with the free local
tool, monetize the team/security/prod layer that a bundled single-user inspector will
never prioritize.** Speed and distribution are the moat, not tech.

---

## Phase 1 — Validate cheaply (Week 0, ~2-4 days) — BEFORE writing the proxy

The riskiest assumptions aren't technical. Spend a few days de-risking demand:

- [ ] **Audit the free official MCP Inspector** hands-on. Write down the 5 concrete
      gaps MCPScope will fill (live passive proxying of a *running agent*, history,
      diff, replay/stub, search). If the gap list is thin → reconsider now.
- [ ] **Survey the pain publicly**: post in Anthropic MCP Discord + MCP GitHub
      Discussions — "how do you debug tool calls today?" Collect 10+ replies.
- [ ] **Landing page + waitlist** (Cloudflare Pages, free): headline *"Charles Proxy
      for your AI tool calls"*, mock GIF, email capture. Share in the same channels.
- [ ] **Gate G0:** ≥25 waitlist signups or clearly resonant replies within a week.
      *Pass → build. Fail → run a fresh discovery cycle instead (`run.py --autopilot`).*

## Phase 2 — Build the MVP (Weeks 1-4, compressed from the brief's 8)

The adversarial SWOT's top risk is Anthropic shipping a first-party inspector — so
launch in 4 weeks with a smaller cut, not 8 with everything.

- [ ] **Wk 1 — Proxy core:** stdio transport wrapper (subprocess stdin/stdout splice)
      teeing JSON-RPC frames to SQLite (sessions, calls, payloads). Build against the
      typed **MCP Python SDK** (protocol-churn insurance). Verify end-to-end with
      Claude Desktop + one real MCP server.
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

## Kill criteria (write them down now, while objective)

- G0 fails (no waitlist/community resonance) → don't build.
- 8 weeks post-launch: WAPS flat AND no team-feature pull → freeze as free OSS.
- Anthropic ships a first-party inspector covering live proxying + history + replay
  *before* MCPScope has a user base → pivot straight to governance/prod or stop.
