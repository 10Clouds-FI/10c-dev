#!/usr/bin/env python3
"""Fetch one issue with optional comments + transitions."""
from __future__ import annotations

import argparse
import json
import re
import sys

from _adf import adf_to_text
from _auth import get, load_creds, use_site

URL_RE = re.compile(r"/browse/([A-Z][A-Z0-9_]*-\d+)")


def normalize_key(s: str) -> str:
    m = URL_RE.search(s)
    return m.group(1) if m else s.strip()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("issue", help="Issue key (ABC-123) or full URL")
    p.add_argument("--with-comments", action="store_true")
    p.add_argument("--with-transitions", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    key = normalize_key(args.issue)
    fields = "summary,status,assignee,reporter,issuetype,priority,labels,description,created,updated,project,parent"
    issue = get(f"/rest/api/3/issue/{key}", query={"fields": fields}, creds=creds)

    payload: dict = {"key": issue["key"], "url": f"{creds['host']}/browse/{issue['key']}", "fields": issue["fields"]}

    if args.with_comments:
        c = get(f"/rest/api/3/issue/{key}/comment", query={"maxResults": 100}, creds=creds) or {}
        payload["comments"] = c.get("comments", [])
    if args.with_transitions:
        t = get(f"/rest/api/3/issue/{key}/transitions", creds=creds) or {}
        payload["transitions"] = t.get("transitions", [])

    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return 0

    f = issue["fields"]
    print(f"{issue['key']}  {payload['url']}")
    print(f"  Summary:   {f.get('summary', '')}")
    print(f"  Status:    {(f.get('status') or {}).get('name')} ({(f.get('status') or {}).get('statusCategory', {}).get('key')})")
    print(f"  Type:      {(f.get('issuetype') or {}).get('name')}")
    print(f"  Priority:  {(f.get('priority') or {}).get('name')}")
    def _person(p: dict) -> str:
        if not p:
            return "Unassigned"
        name = p.get("displayName") or "?"
        email = p.get("emailAddress")
        return f"{name} <{email}>" if email else name
    print(f"  Assignee:  {_person(f.get('assignee') or {})}")
    print(f"  Reporter:  {_person(f.get('reporter') or {})}")
    print(f"  Project:   {(f.get('project') or {}).get('key')} — {(f.get('project') or {}).get('name')}")
    if f.get("labels"):
        print(f"  Labels:    {', '.join(f['labels'])}")
    print(f"  Created:   {f.get('created')}")
    print(f"  Updated:   {f.get('updated')}")
    desc = adf_to_text(f.get("description"))
    if desc:
        print()
        print("Description:")
        for line in desc.split("\n"):
            print(f"  {line}")

    if args.with_comments and payload.get("comments"):
        print()
        print(f"Comments ({len(payload['comments'])}):")
        for c in payload["comments"]:
            author = (c.get("author") or {}).get("displayName", "?")
            print(f"  - {author} @ {c.get('created')}")
            text = adf_to_text(c.get("body"))
            for line in text.split("\n"):
                print(f"      {line}")

    if args.with_transitions and payload.get("transitions"):
        print()
        print("Available transitions:")
        for t in payload["transitions"]:
            print(f"  id={t['id']:>4}  {t['name']:30s}  -> {t['to']['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
