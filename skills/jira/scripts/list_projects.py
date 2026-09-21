#!/usr/bin/env python3
"""List JIRA projects accessible to the user."""
from __future__ import annotations

import argparse
import json
import sys

from _auth import load_creds, use_site
from _paginate import offset_paginate


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--query", help="Substring filter on project key/name (server-side)")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    params: dict = {}
    if args.query:
        params["query"] = args.query
    values, next_start, is_last, total = offset_paginate(
        "/rest/api/3/project/search", params, args.limit, start=args.start, creds=creds
    )

    if args.json:
        out = {
            "total": total,
            "isLast": is_last,
            "nextStart": next_start if not is_last else None,
            "projects": [
                {
                    "key": v.get("key"),
                    "name": v.get("name"),
                    "type": v.get("projectTypeKey"),
                    "style": v.get("style"),
                    "lead": (v.get("lead") or {}).get("displayName"),
                    "url": f"{creds['host']}/browse/{v.get('key')}",
                }
                for v in values
            ],
        }
        print(json.dumps(out, indent=2))
        return 0

    print(f"Projects (total={total}, showing {len(values)}, isLast={is_last}):")
    print()
    for v in values:
        lead = (v.get("lead") or {}).get("displayName") or "-"
        print(f"  {v.get('key', '?'):14s} {v.get('projectTypeKey', '?'):12s} {lead:25s} {v.get('name', '')[:60]}")
    if not is_last:
        print()
        print(f"More results. Next: --start {next_start}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
