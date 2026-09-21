#!/usr/bin/env python3
"""Raw JIRA REST escape hatch. Use when no other script fits."""
from __future__ import annotations

import argparse
import json
import sys

from _auth import request, use_site


def main() -> int:
    p = argparse.ArgumentParser(
        description="Raw JIRA REST passthrough. Adds Basic auth + JSON content-type.",
    )
    p.add_argument("method", choices=["GET", "POST", "PUT", "DELETE", "PATCH"])
    p.add_argument("path", help="API path starting with / (e.g. /rest/api/3/myself)")
    p.add_argument("--body", help="JSON body (string). Mutually exclusive with --body-file.")
    p.add_argument("--body-file", help="Read JSON body from this file")
    p.add_argument("--query", action="append", default=[], help="key=value query param (repeatable)")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    body = None
    if args.body and args.body_file:
        print("--body and --body-file are mutually exclusive", file=sys.stderr)
        return 1
    if args.body:
        body = json.loads(args.body)
    elif args.body_file:
        with open(args.body_file) as f:
            body = json.load(f)

    query = {}
    for kv in args.query:
        if "=" in kv:
            k, v = kv.split("=", 1)
            query[k] = v

    resp = request(args.method, args.path, body=body, query=query or None)
    if resp is None:
        print("(empty response)")
        return 0
    print(json.dumps(resp, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
