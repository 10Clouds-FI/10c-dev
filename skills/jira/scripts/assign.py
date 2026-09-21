#!/usr/bin/env python3
"""Assign an issue. PUT /rest/api/3/issue/{key}/assignee."""
from __future__ import annotations

import argparse
import json
import sys

from _auth import get, load_creds, put, resolve_user, use_site
from get_issue import normalize_key


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("issue", help="Issue key (ABC-123) or full URL")
    p.add_argument("assignee", help="me | -1 (unassign) | <email> | <accountId>")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    key = normalize_key(args.issue)
    account_id = resolve_user(args.assignee, creds=creds)
    body = {"accountId": account_id}
    put(f"/rest/api/3/issue/{key}/assignee", body, creds=creds)

    verify = get(f"/rest/api/3/issue/{key}", query={"fields": "assignee"}, creds=creds)
    actual = ((verify or {}).get("fields", {}).get("assignee") or {})
    name = actual.get("displayName", "Unassigned")
    actual_id = actual.get("accountId")

    url = f"{creds['host']}/browse/{key}"
    if args.json:
        print(json.dumps(
            {"key": key, "assignee_accountId": actual_id, "assignee_name": name, "url": url},
            indent=2,
        ))
        return 0
    print(f"{key} assigned to {name} ({actual_id or 'unassigned'})")
    print(f"  {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
