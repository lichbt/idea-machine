#!/usr/bin/env python3
"""MCPScope Phase-1, Day 3: find outreach targets with demonstrated MCP-debugging pain.

Searches recent GitHub issues for people struggling to debug/inspect MCP tool
calls, and writes a contact list (date, repo, author, title, URL) to
reports/outreach_targets.md. You then comment/DM them yourself — the plan's
template is in action_plan_mcpscope_phase1.md.

Usage:  .venv/bin/python validation_mcpscope/find_outreach_targets.py
Optional: GITHUB_TOKEN raises the search rate limit (10 -> 30/min).
"""
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import requests

DAYS_BACK = 90
MAX_PER_REPO = 2     # diversity: don't fill the list from one repo
TARGET_COUNT = 25

QUERIES = [
    'mcp debug "tool calls" is:issue',
    'mcp inspect traffic is:issue',
    '"mcp server" debugging logging is:issue',
    'mcp proxy observability is:issue',
    'org:modelcontextprotocol debug is:issue',
]
UA = {"User-Agent": "mcpscope-validation/0.1",
      "Accept": "application/vnd.github+json"}
OUT = Path(__file__).resolve().parent.parent / "reports" / "outreach_targets.md"


def headers():
    h = dict(UA)
    tok = os.getenv("GITHUB_TOKEN")
    if tok:
        h["Authorization"] = "Bearer " + tok
    return h


def search(query, since):
    try:
        r = requests.get(
            "https://api.github.com/search/issues",
            params={"q": "%s created:>%s" % (query, since),
                    "sort": "created", "order": "desc", "per_page": 20},
            headers=headers(), timeout=20)
        if r.status_code == 403:
            print("  ! rate-limited on %r — waiting 60s" % query)
            time.sleep(60)
            return search(query, since)
        r.raise_for_status()
        return r.json().get("items", [])
    except requests.RequestException as e:
        print("  ! search failed (%s): %s" % (query, e))
        return []


def repo_of(url):
    # https://github.com/<owner>/<repo>/issues/<n>
    parts = (url or "").split("/")
    return "/".join(parts[3:5]) if len(parts) >= 7 else "?"


# Auto-generated digest/newsletter issues mention our keywords daily but contain
# no human pain — filter them out along with bot authors.
_NOISE_TITLE = ("digest", "daily report", "newsletter", "日报", "动态", "bản tin",
                "weekly", "changelog")


def is_noise(item):
    author = (((item.get("user") or {}).get("login")) or "").lower()
    if author.endswith("[bot]") or author.endswith("-bot"):
        return True
    title = (item.get("title") or "").lower()
    return any(w in title for w in _NOISE_TITLE)


def main():
    since = (datetime.utcnow() - timedelta(days=DAYS_BACK)).strftime("%Y-%m-%d")
    rows, seen_urls, per_repo = [], set(), {}

    for q in QUERIES:
        print("Searching: %r ..." % q)
        for it in search(q, since):
            if is_noise(it):
                continue
            url = it.get("html_url") or ""
            repo = repo_of(url)
            if url in seen_urls or per_repo.get(repo, 0) >= MAX_PER_REPO:
                continue
            seen_urls.add(url)
            per_repo[repo] = per_repo.get(repo, 0) + 1
            rows.append({
                "date": (it.get("created_at") or "")[:10],
                "repo": repo,
                "author": ((it.get("user") or {}).get("login")) or "?",
                "title": (it.get("title") or "").replace("|", "/")[:80],
                "url": url,
                "comments": it.get("comments", 0),
            })
        if len(rows) >= TARGET_COUNT:
            break
        time.sleep(7)  # unauth search rate limit

    rows.sort(key=lambda r: r["date"], reverse=True)
    rows = rows[:TARGET_COUNT]

    lines = [
        "# Outreach targets — generated %s" % datetime.now().strftime("%Y-%m-%d"),
        "",
        "Recent GitHub issues showing MCP-debugging pain (last %d days)." % DAYS_BACK,
        "Comment on the issue or DM the author — template in "
        "action_plan_mcpscope_phase1.md (Day 3). Log replies in the scorecard.",
        "",
        "| date | repo | author | issue | 💬 |",
        "|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append("| %s | %s | @%s | [%s](%s) | %d |" % (
            r["date"], r["repo"], r["author"], r["title"], r["url"],
            r["comments"]))
    lines += ["", "Contacted / replied tracker:", ""]
    for r in rows[:10]:
        lines.append("- [ ] @%s — sent: ____  reply: ____" % r["author"])

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("\n%d targets -> %s" % (len(rows), OUT))


if __name__ == "__main__":
    sys.exit(main())
