"""Two paginators: JQL search uses nextPageToken; everything else uses startAt/maxResults."""
from __future__ import annotations

from typing import Any, Iterator

from _auth import get, post


def cursor_paginate(
    path: str,
    body: dict[str, Any],
    limit: int,
    cursor: str | None = None,
    creds: dict[str, Any] | None = None,
) -> tuple[list[Any], str | None, bool]:
    """One page from a nextPageToken endpoint (e.g. /search/jql). Returns (issues, nextPageToken, isLast)."""
    payload = dict(body)
    payload["maxResults"] = limit
    if cursor:
        payload["nextPageToken"] = cursor
    resp = post(path, payload, creds=creds)
    issues = resp.get("issues", []) if isinstance(resp, dict) else []
    return issues, resp.get("nextPageToken"), bool(resp.get("isLast", False))


def offset_paginate(
    path: str,
    params: dict[str, Any],
    limit: int,
    start: int = 0,
    creds: dict[str, Any] | None = None,
) -> tuple[list[Any], int, bool, int | None]:
    """One page from a startAt/maxResults endpoint. Returns (values, next_start, isLast, total)."""
    q = dict(params)
    q["startAt"] = start
    q["maxResults"] = limit
    resp = get(path, query=q, creds=creds)
    if not isinstance(resp, dict):
        return [], start, True, None
    values = resp.get("values") or resp.get("issues") or []
    total = resp.get("total")
    is_last = resp.get("isLast")
    if is_last is None and total is not None:
        is_last = (start + len(values)) >= total
    if is_last is None:
        is_last = len(values) < limit
    return values, start + len(values), bool(is_last), total
