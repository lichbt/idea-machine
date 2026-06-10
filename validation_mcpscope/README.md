# MCPScope — Phase 1 Validation Kit

Automates the automatable parts of
[`reports/action_plan_mcpscope_phase1.md`](../reports/action_plan_mcpscope_phase1.md).
Self-contained — lift this folder into MCPScope's own repo later.

| Plan step | Tool here | Run |
|---|---|---|
| Day 1 AM — competitor sweep + name check | `competitor_sweep.py` | `.venv/bin/python validation_mcpscope/competitor_sweep.py` |
| Day 1 AM — hands-on Inspector audit | *(manual)* | `npx @modelcontextprotocol/inspector <server-cmd>` |
| Day 1 PM — landing page + waitlist | `landing/index.html` | see Deploy below |
| Day 2 — community pain survey | *(manual — drafts in the plan)* | — |
| Day 3 — outreach target list | `find_outreach_targets.py` | `.venv/bin/python validation_mcpscope/find_outreach_targets.py` |
| Day 3-4 — G0 scorecard + decision | *(manual — table in the plan)* | — |

Both scripts write reports into `../reports/` (`competitor_sweep.md`,
`outreach_targets.md`). Optional `GITHUB_TOKEN` env var raises the GitHub search
rate limit; without it the scripts self-throttle (~7s between queries).

## Deploy the landing page

1. Get a form endpoint: create a free form at formspree.io and replace
   `YOUR_FORM_ID` in `landing/index.html` (or swap in a Tally/Buttondown embed).
2. Replace the `hello@example.com` footer address.
3. Confirm the three feature cards against the Inspector audit findings.
4. Deploy (pick one):
   - **Drag-and-drop:** Cloudflare Pages dashboard → Create → Upload assets → drop
     the `landing/` folder.
   - **CLI:** `npx wrangler pages deploy validation_mcpscope/landing --project-name mcpscope`
5. Optional: enable Cloudflare Web Analytics and paste its snippet into the footer.

## What stays manual (on purpose)

Posting to Discord/Reddit/GitHub and DMing people — the drafts live in the plan;
sending them as a human is both the ethical move and the better signal.
