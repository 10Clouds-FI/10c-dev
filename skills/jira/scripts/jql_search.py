#!/usr/bin/env python3
"""Raw JQL search via /rest/api/3/search/jql."""
from __future__ import annotations

import argparse
import json
import sys

from _auth import load_creds, use_site
from _paginate import cursor_paginate

DEFAULT_FIELDS = "summary,status,assignee,issuetype,priority,updated,project"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("jql", help="JQL query string")
    p.add_argument("--fields", default=DEFAULT_FIELDS, help="Comma-separated field list (default: %(default)s)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--cursor")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    body = {"jql": args.jql, "fields": [f.strip() for f in args.fields.split(",") if f.strip()]}
    issues, next_token, is_last = cursor_paginate(
        "/rest/api/3/search/jql", body, args.limit, cursor=args.cursor, creds=creds
    )

    if args.json:
        out = {
            "jql": args.jql,
            "count": len(issues),
            "isLast": is_last,
            "nextPageToken": next_token,
            "issues": [
                {"key": i["key"], "fields": i["fields"], "url": f"{creds['host']}/browse/{i['key']}"}
                for i in issues
            ],
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"JQL: {args.jql}")
    print(f"Showing {len(issues)} issues (isLast={is_last})")
    print()
    for i in issues:
        f = i["fields"]
        status = (f.get("status") or {}).get("name", "?")
        assignee = (f.get("assignee") or {}).get("displayName", "Unassigned")
        print(f"  {i['key']:14s} [{status:20s}] {assignee:25s} {f.get('summary', '')[:60]}")
    if not is_last and next_token:
        print()
        print(f"More results. Next: --cursor {next_token}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
