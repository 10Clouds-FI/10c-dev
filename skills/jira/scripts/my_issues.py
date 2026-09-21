#!/usr/bin/env python3
"""List issues assigned to me. JQL: assignee = currentUser()."""
from __future__ import annotations

import argparse
import json
import sys

from _auth import load_creds, use_site
from _paginate import cursor_paginate


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--status", help='Filter by status name (e.g. "In Progress")')
    p.add_argument("--project", help="Filter by project key (e.g. ABC)")
    p.add_argument("--include-done", action="store_true", help="Include resolved/Done issues")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--cursor")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    jql_parts = ["assignee = currentUser()"]
    if not args.include_done:
        jql_parts.append("statusCategory != Done")
    if args.status:
        jql_parts.append(f'status = "{args.status}"')
    if args.project:
        jql_parts.append(f"project = {args.project}")
    jql = " AND ".join(jql_parts) + " ORDER BY updated DESC"

    body = {
        "jql": jql,
        "fields": ["summary", "status", "assignee", "issuetype", "priority", "updated", "project"],
    }
    issues, next_token, is_last = cursor_paginate(
        "/rest/api/3/search/jql", body, args.limit, cursor=args.cursor, creds=creds
    )

    if args.json:
        out = {
            "jql": jql,
            "count": len(issues),
            "isLast": is_last,
            "nextPageToken": next_token,
            "issues": [
                {
                    "key": i["key"],
                    "summary": i["fields"].get("summary", ""),
                    "status": (i["fields"].get("status") or {}).get("name"),
                    "type": (i["fields"].get("issuetype") or {}).get("name"),
                    "priority": (i["fields"].get("priority") or {}).get("name"),
                    "updated": i["fields"].get("updated"),
                    "url": f"{creds['host']}/browse/{i['key']}",
                }
                for i in issues
            ],
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"JQL: {jql}")
    print(f"Showing {len(issues)} issues (isLast={is_last})")
    print()
    for i in issues:
        f = i["fields"]
        status = (f.get("status") or {}).get("name", "?")
        itype = (f.get("issuetype") or {}).get("name", "?")
        print(f"  {i['key']:14s} [{status:20s}] {itype:8s} {f.get('summary', '')[:80]}")
    if not is_last and next_token:
        print()
        print(f"More results available. Re-run with: --cursor {next_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
