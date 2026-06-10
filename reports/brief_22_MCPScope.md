# Build Brief — MCPScope

## MVP scope

A pip-installable CLI proxy that sits in front of any MCP server, captures every JSON-RPC tool call to SQLite, and renders a live Textual TUI showing call stream, latency, and payload diff — fully local, zero signup required.

## First features (build order)

- Transparent stdio/SSE proxy core: intercepts MCP JSON-RPC 2.0 messages between any client and server, records request+response+latency to SQLite with zero config changes to the target agent
- Textual TUI: scrollable live feed of tool calls, color-coded by status (ok/error/timeout), with a detail pane showing full payload on arrow-key selection
- Search and filter bar in TUI: filter visible calls by tool name, status code, or substring in payload using a single-keystroke / prompt
- mcpscope replay <call-id>: re-execute any logged call against the live server from the CLI, printing response diff against the original
- mcpscope export <session-id>: dump a session to a portable JSON file that can be shared and re-imported for offline stub replay

## Tech stack

Python 3.11+: asyncio for the proxy (handles both stdio and SSE transports), Textual for the TUI (handles reactive state cleanly), SQLite via aiosqlite for local session storage, Typer for CLI entry points, httpx for SSE transport passthrough. Packaged as a single pip install with a pyproject.toml. Paid tier later: Cloudflare Workers (session upload API) + R2 (payload storage) + D1 (metadata).

## Build steps (≤ 8 weeks)

- Week 1: Proxy core — implement stdio transport wrapper (subprocess stdin/stdout splice) that tees JSON-RPC frames to an async queue; write SQLite schema (sessions, calls, payloads); verify end-to-end capture with claude-desktop + one real MCP server
- Week 2: SSE transport support + CLI entry point — `mcpscope run --stdio <cmd>` and `mcpscope run --sse <url>`; add token-cost estimation from model name header if present; write pytest fixtures for both transports
- Week 3: Textual TUI v1 — live-updating DataTable of calls (tool name, status, latency, timestamp), detail pane with JSON pretty-print, auto-scroll toggle; confirm it works inside tmux and VS Code terminal
- Week 4: Search/filter + diff view — single-keystroke filter bar, sequential-call diff highlighting (show changed keys between call N and N-1 for same tool), status-code color coding
- Week 5: Replay + export — `mcpscope replay`, `mcpscope stub` (serve saved response without hitting live server), `mcpscope export/import` JSON; this is the offline bug-reproduction story
- Week 6: Packaging + DX polish — `pip install mcpscope` works cleanly, auto-detects claude-desktop config to offer one-liner install, README with 3 copy-paste quickstart examples, record a 90-second terminal demo GIF
- Week 7: Landing page + waitlist for paid tier — single static page (Cloudflare Pages), headline + demo GIF + email capture; set up Cloudflare Workers skeleton for future session upload API
- Week 8: Launch — Show HN post, post to r/LocalLLaMA and r/MachineLearning, share in Anthropic MCP Discord and Model Context Protocol GitHub Discussions; collect friction feedback and cut a v0.2 patch

## Wedge

Zero-friction local setup with no account, no cloud dependency, and no SDK lock-in — works with any MCP client in under 60 seconds via a single pip install, while New Relic requires an enterprise contract, LangSmith only covers LangChain agents, and Langfuse requires a cloud account before you see a single trace.

## Landing page

**Charles Proxy for your AI tool calls.**

MCPScope intercepts every MCP tool invocation locally — inspect payloads, replay bugs offline, and ship AI agents without flying blind. Free forever, nothing leaves your machine.

## First 10 users

Post a 'Show HN' with the demo GIF on day of first working build; drop it in the #mcp-dev channel of the Anthropic Discord and the Model Context Protocol GitHub Discussions thread; reply to the top 3 open GitHub issues tagged 'debugging' in popular MCP server repos (mcp-server-filesystem, mcp-server-git); DM 5 developers who have publicly tweeted about MCP debugging pain in the last 30 days.

## Top risks & de-risking

- Anthropic ships a first-party MCP inspector inside Claude Desktop within 6-8 weeks, removing the immediate pain: de-risk by launching within 4 weeks (working proxy + TUI is enough), getting early users on record, and pivoting to team/cross-session features that a bundled inspector will never prioritize.
- MCP protocol evolves fast (transport changes, auth layers) and breaks the proxy core: de-risk by building against the typed MCP Python SDK for message parsing rather than raw bytes, and subscribing to the spec repo releases so you can ship a patch within 24 hours of a breaking change.
- Market is tiny today and stalls before paid tier gets traction: de-risk by keeping the free tier genuinely excellent (open-core is the acquisition channel), pricing the paid tier as an easy team expense ($49/mo), and measuring weekly active proxied sessions rather than signups — if that number doubles monthly through August, paid conversion follows.
