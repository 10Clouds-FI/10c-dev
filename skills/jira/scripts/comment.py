#!/usr/bin/env python3
"""Add a comment to an issue."""
from __future__ import annotations

import argparse
import json
import sys

from _adf import text_to_adf
from _auth import load_creds, post, use_site
from get_issue import normalize_key


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("issue", help="Issue key (ABC-123) or full URL")
    p.add_argument("body", help="Comment text (plain — wrapped in ADF automatically)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()
    key = normalize_key(args.issue)
    resp = post(f"/rest/api/3/issue/{key}/comment", {"body": text_to_adf(args.body)}, creds=creds)
    if not isinstance(resp, dict) or "id" not in resp:
        print("Unexpected response shape:", file=sys.stderr)
        print(json.dumps(resp, indent=2), file=sys.stderr)
        return 1

    url = f"{creds['host']}/browse/{key}?focusedCommentId={resp['id']}"
    if args.json:
        print(json.dumps({"comment_id": resp["id"], "created": resp.get("created"), "url": url}, indent=2))
        return 0
    print(f"Comment posted on {key}.")
    print(f"  id:      {resp['id']}")
    print(f"  created: {resp.get('created')}")
    print(f"  url:     {url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
