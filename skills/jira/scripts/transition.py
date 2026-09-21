#!/usr/bin/env python3
"""Transition an issue. GET /transitions to discover, POST with matched id."""
from __future__ import annotations

import argparse
import json
import sys

from _auth import get, load_creds, post, use_site
from get_issue import normalize_key


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("issue", help="Issue key (ABC-123) or full URL")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--to", help='Transition name (case-insensitive substring match, e.g. "in progress")')
    g.add_argument("--id", help="Transition id (use --list to discover)")
    g.add_argument("--list", action="store_true", help="Just list available transitions and exit")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    key = normalize_key(args.issue)

    t_resp = get(f"/rest/api/3/issue/{key}/transitions", creds=creds) or {}
    transitions = t_resp.get("transitions", [])

    if args.list or (not args.to and not args.id):
        if args.json:
            print(json.dumps(transitions, indent=2))
            return 0
        print(f"Available transitions for {key}:")
        for t in transitions:
            print(f"  id={t['id']:>4}  {t['name']:30s}  -> {t['to']['name']}")
        return 0

    if args.id:
        target = next((t for t in transitions if str(t["id"]) == str(args.id)), None)
        if not target:
            print(f"Transition id {args.id} not available for {key}. Available:", file=sys.stderr)
            for t in transitions:
                print(f"  id={t['id']}  {t['name']}", file=sys.stderr)
            return 1
    else:
        needle = args.to.lower()
        matches = [t for t in transitions if needle in t["name"].lower()]
        if not matches:
            print(f"No transition matching {args.to!r} for {key}. Available:", file=sys.stderr)
            for t in transitions:
                print(f"  - {t['name']}", file=sys.stderr)
            return 1
        if len(matches) > 1:
            print(f"Ambiguous match for {args.to!r}:", file=sys.stderr)
            for t in matches:
                print(f"  - {t['name']}", file=sys.stderr)
            return 1
        target = matches[0]

    post(
        f"/rest/api/3/issue/{key}/transitions",
        {"transition": {"id": str(target["id"])}},
        creds=creds,
    )

    url = f"{creds['host']}/browse/{key}"
    if args.json:
        print(json.dumps({"key": key, "transitioned_to": target["to"]["name"], "url": url}, indent=2))
        return 0
    print(f"{key} transitioned via {target['name']!r} -> {target['to']['name']}")
    print(f"  {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
