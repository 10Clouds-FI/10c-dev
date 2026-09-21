#!/usr/bin/env python3
"""Create a JIRA issue. POST /rest/api/3/issue."""
from __future__ import annotations

import argparse
import json
import sys

from _adf import text_to_adf
from _auth import load_creds, post, resolve_user, use_site


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--project", required=True, help="Project key (e.g. ABC)")
    p.add_argument("--type", default="Task", help="Issue type name (Task, Bug, Story, Epic, Subtask, ...)")
    p.add_argument("--summary", required=True)
    p.add_argument("--description", default="", help="Plain text — wrapped in ADF automatically")
    p.add_argument("--assignee", help="me | <email> | <accountId>")
    p.add_argument("--labels", help="Comma-separated label list")
    p.add_argument("--parent", help="Parent issue key (for subtasks or epics)")
    p.add_argument("--priority", help="Priority name (Highest, High, Medium, Low, Lowest)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    fields: dict = {
        "project": {"key": args.project},
        "issuetype": {"name": args.type},
        "summary": args.summary,
    }
    if args.description:
        fields["description"] = text_to_adf(args.description)
    if args.assignee:
        account_id = resolve_user(args.assignee, creds=creds)
        fields["assignee"] = {"accountId": account_id} if account_id else None
    if args.labels:
        fields["labels"] = [l.strip() for l in args.labels.split(",") if l.strip()]
    if args.parent:
        fields["parent"] = {"key": args.parent}
    if args.priority:
        fields["priority"] = {"name": args.priority}

    resp = post("/rest/api/3/issue", {"fields": fields}, creds=creds)
    if not isinstance(resp, dict) or "key" not in resp:
        print("Unexpected response shape:", file=sys.stderr)
        print(json.dumps(resp, indent=2), file=sys.stderr)
        return 1

    url = f"{creds['host']}/browse/{resp['key']}"
    if args.json:
        print(json.dumps({"key": resp["key"], "id": resp.get("id"), "url": url}, indent=2))
        return 0
    print(f"Created {resp['key']}  {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
