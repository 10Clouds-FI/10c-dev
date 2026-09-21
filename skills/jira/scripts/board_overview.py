#!/usr/bin/env python3
"""Board snapshot. Auto-detects kanban vs scrum and routes accordingly."""
from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict

from _auth import get, load_creds, use_site


def find_board_by_project(project_key: str, creds: dict) -> dict | None:
    resp = get("/rest/agile/1.0/board", query={"projectKeyOrId": project_key}, creds=creds)
    if not isinstance(resp, dict):
        return None
    values = resp.get("values") or []
    return values[0] if values else None


def kanban_overview(board: dict, board_id: int, creds: dict) -> dict:
    config = get(f"/rest/agile/1.0/board/{board_id}/configuration", creds=creds) or {}
    columns = config.get("columnConfig", {}).get("columns", [])
    status_to_column = {}
    for col in columns:
        for st in col.get("statuses", []):
            status_to_column[st["id"]] = col["name"]

    buckets: OrderedDict[str, list] = OrderedDict((c["name"], []) for c in columns)
    start = 0
    total = None
    while True:
        page = get(
            f"/rest/agile/1.0/board/{board_id}/issue",
            query={"startAt": start, "maxResults": 100, "fields": "summary,status,assignee,updated"},
            creds=creds,
        ) or {}
        issues = page.get("issues", [])
        total = page.get("total")
        for i in issues:
            status_id = ((i["fields"].get("status") or {}).get("id"))
            col_name = status_to_column.get(status_id, "(uncategorized)")
            if col_name not in buckets:
                buckets[col_name] = []
            buckets[col_name].append(i)
        start += len(issues)
        if total is None or start >= total or not issues:
            break

    return {
        "board": {"id": board_id, "name": board["name"], "type": board["type"]},
        "total_issues": total,
        "columns": [
            {
                "name": name,
                "count": len(items),
                "top": [
                    {
                        "key": i["key"],
                        "summary": (i["fields"].get("summary") or "")[:80],
                        "assignee": ((i["fields"].get("assignee") or {}).get("displayName")) or "Unassigned",
                    }
                    for i in items[:3]
                ],
            }
            for name, items in buckets.items()
        ],
    }


def scrum_overview(board: dict, board_id: int, creds: dict) -> dict:
    sprints_resp = get(f"/rest/agile/1.0/board/{board_id}/sprint", query={"state": "active,future"}, creds=creds) or {}
    sprints = sprints_resp.get("values", [])
    out_sprints = []
    for s in sprints:
        issues_resp = get(
            f"/rest/agile/1.0/sprint/{s['id']}/issue",
            query={"fields": "summary,status,assignee", "maxResults": 100},
            creds=creds,
        ) or {}
        issues = issues_resp.get("issues", [])
        out_sprints.append({
            "id": s["id"],
            "name": s["name"],
            "state": s["state"],
            "startDate": s.get("startDate"),
            "endDate": s.get("endDate"),
            "goal": s.get("goal"),
            "issue_count": len(issues),
            "by_status": _group_by_status(issues),
        })
    return {
        "board": {"id": board_id, "name": board["name"], "type": board["type"]},
        "sprints": out_sprints,
    }


def _group_by_status(issues: list) -> dict:
    out: dict[str, list] = {}
    for i in issues:
        st = ((i["fields"].get("status") or {}).get("name")) or "?"
        out.setdefault(st, []).append({"key": i["key"], "summary": (i["fields"].get("summary") or "")[:80]})
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument("--board", type=int, help="Board id")
    g.add_argument("--project", help="Project key (resolves to its first board)")
    p.add_argument("--json", action="store_true")
    p.add_argument("--site", help="Jira site URL or host (default: JIRA_SITE, .claude/task-flow.json, or the stored setup)")
    args = p.parse_args()
    use_site(args.site)

    creds = load_creds()

    board_id = args.board
    if not board_id and args.project:
        board = find_board_by_project(args.project, creds)
        if not board:
            print(f"No board found for project {args.project}", file=sys.stderr)
            return 1
        board_id = board["id"]
    if not board_id:
        print("Pass --board <id> or --project <KEY>.", file=sys.stderr)
        return 1

    config = get(f"/rest/agile/1.0/board/{board_id}/configuration", creds=creds) or {}
    board_meta = {"name": config.get("name", "?"), "type": config.get("type", "?")}

    if board_meta["type"] == "scrum":
        result = scrum_overview(board_meta, board_id, creds)
    else:
        result = kanban_overview(board_meta, board_id, creds)

    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    b = result["board"]
    loc = config.get("location") or {}
    project_key = loc.get("projectKey") or loc.get("key") or "?"
    print(f"Board: {b['name']} (id={b['id']}, type={b['type']})")
    print(f"URL:   {creds['host']}/jira/software/projects/{project_key}/boards/{b['id']}")
    print()
    if board_meta["type"] == "scrum":
        for s in result["sprints"]:
            print(f"Sprint: {s['name']} ({s['state']}, {s['issue_count']} issues)")
            if s.get("goal"):
                print(f"  Goal: {s['goal']}")
            for status, items in s["by_status"].items():
                print(f"  {status} ({len(items)}):")
                for it in items[:5]:
                    print(f"    {it['key']:14s} {it['summary']}")
            print()
    else:
        total = result.get("total_issues")
        print(f"Total issues on board: {total}")
        print()
        for col in result["columns"]:
            print(f"  {col['name']} ({col['count']})")
            for t in col["top"]:
                print(f"    {t['key']:14s} {t['assignee']:25s} {t['summary']}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
