"""Plain text -> minimal Atlassian Document Format. v1: paragraphs only."""
from __future__ import annotations

from typing import Any


def text_to_adf(text: str) -> dict[str, Any]:
    paragraphs = [p for p in text.split("\n\n")]
    content = []
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": para}],
        })
    if not content:
        content.append({"type": "paragraph", "content": []})
    return {"type": "doc", "version": 1, "content": content}


def adf_to_text(adf: dict[str, Any] | None) -> str:
    if not adf or not isinstance(adf, dict):
        return ""
    parts: list[str] = []
    _walk_adf(adf, parts)
    return "\n".join(p for p in parts if p)


def _walk_adf(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        ntype = node.get("type")
        if ntype == "text":
            out.append(node.get("text", ""))
            return
        if ntype == "hardBreak":
            out.append("\n")
            return
        children = node.get("content") or []
        if ntype == "paragraph":
            buf: list[str] = []
            for c in children:
                _walk_adf_inline(c, buf)
            out.append("".join(buf))
            return
        if ntype == "heading":
            level = node.get("attrs", {}).get("level", 1)
            buf: list[str] = []
            for c in children:
                _walk_adf_inline(c, buf)
            out.append("#" * level + " " + "".join(buf))
            return
        if ntype in ("bulletList", "orderedList"):
            for c in children:
                _walk_adf(c, out)
            return
        if ntype == "listItem":
            buf: list[str] = []
            for c in children:
                _walk_adf_inline(c, buf)
            out.append("- " + "".join(buf))
            return
        for c in children:
            _walk_adf(c, out)


def _walk_adf_inline(node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("type") == "text":
            out.append(node.get("text", ""))
            return
        for c in node.get("content") or []:
            _walk_adf_inline(c, out)
