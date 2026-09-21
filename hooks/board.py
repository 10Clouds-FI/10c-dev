#!/usr/bin/env python3
"""Agent awareness board: parallel Claude Code sessions on one machine see each other.

One JSON file per live Claude Code session under ~/.claude/10c-dev/board/<repo-id>/, written
only by that session's hooks. Liveness comes from Claude Code's own registry in
~/.claude/sessions/<pid>.json plus a pid check, so there is no TTL to tune.

Hook commands (stdin = the hook's JSON), wired in hooks/hooks.json:

    register    SessionStart      create the record, print the neighbour digest
    prompt      UserPromptSubmit  guess the ticket key from the prompt, print the digest if changed
    touch       PostToolUse       Edit/Write/...: record the file; hotspot -> blocker
    pre-bash    PreToolUse Bash   snapshot dirty files; "ask" before git push / a stack command
                                  when a neighbour is in the way
    post-bash   PostToolUse Bash  attribute files the command changed; digest as additionalContext
    end         SessionEnd        remove the record

CLI (session from $CLAUDE_CODE_SESSION_ID when needed):

    overview [--json]                 live sessions on this repo
    overlap                           files this session and a neighbour both touch
    check-stack | check-push          exit 1 and explain when a neighbour holds the blocker
    set --ticket K | --phase P | --blocker T [--note N] | --clear-blocker T

Per-repo configuration lives in `<repo>/.claude/task-flow.json`:

    hotspots       array of fnmatch globs, relative to the repo root, for files where two
                   parallel changes reliably collide (lockfiles, migrations, shared routers).
                   Touching one puts a "hotspot" blocker on the session, so neighbours see it.
                   Falls back to `<repo>/.claude/hotspots.txt` (one glob per line, `#` comments)
                   when the key is absent; an empty list when neither exists.
    stackCommands  array of regexes or plain command prefixes that mean "this restarts the
                   shared local stack", e.g. ["make start", "docker compose down"]. Each entry
                   is matched at the start of a shell command (after `;`, `&&`, `|` or `(`).
                   Defaults to `make (start|stop|restart|recreate|down|nuke)` and
                   `docker compose (up|down|restart)`.

Every command fails open: a broken board prints one stderr line and exits 0.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone

# `datetime.UTC` arrived in 3.11; hosts that still run 3.10 as `python3` exist,
# and an ImportError here fires before the fail-open guard below has a chance to.
UTC = timezone.utc
from pathlib import Path

CLAUDE_HOME = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))
SESSIONS_DIR = CLAUDE_HOME / "sessions"
BOARD_ROOT = CLAUDE_HOME / "10c-dev" / "board"
CONFIG_FILE = Path(".claude") / "task-flow.json"
HOTSPOTS_FALLBACK_FILE = Path(".claude") / "hotspots.txt"
TICKET_RE = re.compile(r"\b([A-Z][A-Z0-9]{1,9}-\d{1,6})\b")
# The subcommand right after `git` (flags allowed), so a commit message or an echo
# that merely mentions "push" does not trigger the guard.
PUSH_RE = re.compile(r"(?:^|[;&|(]\s*)git\b[^;&|\n]*?\bpush\b", re.MULTILINE)
# Same anchoring for stack commands; entries come from task-flow.json `stackCommands`.
DEFAULT_STACK_COMMANDS = [
    r"make\b[^;&|\n]*?\b(?:start|stop|restart|recreate|down|nuke)\b",
    r"docker\s+compose\b[^;&|\n]*?\b(?:up|down|restart)\b",
]
STACK_PREFIX = r"(?:^|[;&|(]\s*)"
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MAX_FILES_SHOWN = 3
STACK_BLOCKER = "stack-in-use"
PUSH_BLOCKER = "pushing-main"
HOTSPOT_BLOCKER = "hotspot"


def now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def git(cwd: str, *args: str) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""

    return out.stdout.rstrip("\n") if out.returncode == 0 else ""


def common_dir(cwd: str) -> Path | None:
    common = git(cwd, "rev-parse", "--git-common-dir")
    if not common:
        return None
    path = Path(common)
    if not path.is_absolute():
        path = Path(cwd) / path

    return path.resolve()


def repo_id(cwd: str) -> str:
    common = common_dir(cwd)
    if common is None:
        return "no-repo"

    return hashlib.sha1(str(common).encode()).hexdigest()[:12]


def repo_name(cwd: str) -> str:
    common = common_dir(cwd)

    return common.parent.name if common else Path(cwd).name


def toplevel(cwd: str) -> str:
    return git(cwd, "rev-parse", "--show-toplevel") or cwd


def rel(path: str, cwd: str) -> str:
    top = os.path.realpath(toplevel(cwd))
    real = os.path.realpath(path)
    if real.startswith(top + "/"):
        return real[len(top) + 1 :]

    return path


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True

    return True


def registry() -> dict[str, dict]:
    """session_id -> Claude Code's own session record, live pids only."""
    out: dict[str, dict] = {}
    if not SESSIONS_DIR.is_dir():
        return out
    for path in SESSIONS_DIR.glob("*.json"):
        try:
            rec = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        sid = rec.get("sessionId")
        if sid and pid_alive(int(rec.get("pid") or 0)):
            out[sid] = rec

    return out


def board_dir(cwd: str) -> Path:
    return BOARD_ROOT / repo_id(cwd)


def own_path(cwd: str, sid: str) -> Path:
    return board_dir(cwd) / f"{sid}.json"


def load(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def save(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rec["updated_at"] = now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, ensure_ascii=False))
    tmp.replace(path)


def own_record(hook: dict) -> tuple[Path, dict]:
    sid = hook.get("session_id", "")
    cwd = hook.get("cwd") or os.getcwd()
    path = own_path(cwd, sid)
    rec = load(path)
    reg = registry().get(sid, {})
    rec.update(
        {
            "session_id": sid,
            "pid": reg.get("pid", rec.get("pid")),
            "name": reg.get("name") or rec.get("name") or sid[:8],
            "cwd": cwd,
            "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD") or rec.get("branch", ""),
        }
    )
    rec.setdefault("ticket", None)
    rec.setdefault("phase", "idle")
    rec.setdefault("blockers", [])
    rec.setdefault("files", {})
    rec.setdefault("started_at", now())

    return path, rec


def live_records(cwd: str) -> list[dict]:
    """All live sessions on this repo; prunes records whose session is gone."""
    reg = registry()
    out = []
    for path in board_dir(cwd).glob("*.json"):
        rec = load(path)
        sid = rec.get("session_id")
        if sid not in reg:
            path.unlink(missing_ok=True)
            continue
        rec["status"] = reg[sid].get("status", "")
        rec["name"] = reg[sid].get("name") or rec.get("name") or sid[:8]
        out.append(rec)

    return sorted(out, key=lambda r: r.get("started_at", ""))


def neighbours(cwd: str, me: str) -> list[dict]:
    return [r for r in live_records(cwd) if r.get("session_id") != me]


def holders(cwd: str, me: str, kind: str) -> list[tuple[dict, dict]]:
    return [(r, b) for r in neighbours(cwd, me) for b in r.get("blockers", []) if b["type"] == kind]


# --- per-repo configuration ----------------------------------------------------------------


def config(cwd: str) -> dict:
    """`<repo>/.claude/task-flow.json`, or {} when it is missing or unreadable."""
    data = load(Path(toplevel(cwd)) / CONFIG_FILE)

    return data if isinstance(data, dict) else {}


def hotspots(cwd: str) -> list[str]:
    """Globs from task-flow.json `hotspots`, else `.claude/hotspots.txt`, else nothing."""
    configured = config(cwd).get("hotspots")
    if isinstance(configured, list):
        return [str(p).strip() for p in configured if str(p).strip()]
    try:
        lines = (Path(toplevel(cwd)) / HOTSPOTS_FALLBACK_FILE).read_text().splitlines()
    except OSError:
        return []

    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]


def is_hotspot(path: str, cwd: str) -> bool:
    return any(fnmatch.fnmatch(path, pat) for pat in hotspots(cwd))


def stack_commands(cwd: str) -> list[str]:
    configured = config(cwd).get("stackCommands")
    if isinstance(configured, list):
        entries = [str(c).strip() for c in configured if str(c).strip()]
        if entries:
            return entries

    return DEFAULT_STACK_COMMANDS


def is_stack_command(command: str, cwd: str) -> bool:
    for entry in stack_commands(cwd):
        try:
            pattern = re.compile(STACK_PREFIX + "(?:" + entry + ")", re.MULTILINE)
        except re.error:
            pattern = re.compile(STACK_PREFIX + "(?:" + re.escape(entry) + ")", re.MULTILINE)
        if pattern.search(command):
            return True

    return False


# --- board record helpers -------------------------------------------------------------------


def add_blocker(rec: dict, kind: str, note: str = "") -> None:
    for b in rec["blockers"]:
        if b["type"] == kind:
            if note:
                b["note"] = note

            return
    b = {"type": kind, "since": now()}
    if note:
        b["note"] = note
    rec["blockers"].append(b)


def clear_blocker(rec: dict, kind: str) -> None:
    rec["blockers"] = [b for b in rec["blockers"] if b["type"] != kind]


def record_file(rec: dict, path: str) -> None:
    relp = rel(path, rec["cwd"])
    rec["files"][relp] = now()
    if rec.get("phase") in ("idle", "designing"):
        rec["phase"] = "implementing"
    if is_hotspot(relp, rec["cwd"]):
        add_blocker(rec, HOTSPOT_BLOCKER, relp)


def digest(cwd: str, me: str) -> str:
    others = neighbours(cwd, me)
    if not others:
        return ""
    my_files = set(load(own_path(cwd, me)).get("files", {})) if me else set()
    lines = [f"[agents on this machine · {repo_name(cwd)} · {len(others)} other session(s)]"]
    overlaps = []
    for r in others:
        files = r.get("files", {})
        recent = sorted(files, key=files.get, reverse=True)
        shown = ", ".join(Path(f).name for f in recent[:MAX_FILES_SHOWN])
        files_txt = f"{len(files)} files" + (f" (last: {shown})" if shown else "")
        ticket = (r.get("ticket") or {}).get("key") or "—"
        blockers = " ".join(
            f"BLOCKER {b['type']}" + (f' "{b["note"]}"' if b.get("note") else "")
            for b in r.get("blockers", [])
        )
        lines.append(
            f"  {r['name']:<24} {ticket:<9} {r.get('phase', 'idle'):<13} "
            f"{r.get('branch', '?'):<28} {files_txt}  {blockers}  {r.get('status', '')}".rstrip()
        )
        if not me:
            continue
        for f in sorted(my_files & set(files)):
            overlaps.append(f"  overlap with you: {f} (also edited by {r['name']})")
        if r.get("cwd") == cwd:
            lines.append(
                f"  WARNING: {r['name']} works in the same checkout as you; "
                "a push from either of you carries the other's commits"
            )
    lines.extend(overlaps)
    lines.append(
        "  Before touching shared files: read that session's transcript or message it by name "
        "(ListAgents / SendMessage). Do not restart the local stack or push to main while a "
        "neighbour holds a BLOCKER."
    )

    return "\n".join(lines)


def digest_if_changed(path: Path, rec: dict) -> str:
    text = digest(rec["cwd"], rec["session_id"])
    h = hashlib.sha1(text.encode()).hexdigest() if text else ""
    changed = h != rec.get("last_digest_hash", "")
    rec["last_digest_hash"] = h
    save(path, rec)

    return text if text and changed else ""


def emit(event: str, **fields: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, **fields}}))


def dirty_snapshot(cwd: str) -> dict[str, float]:
    top = toplevel(cwd)
    out: dict[str, float] = {}
    status = git(cwd, "status", "--porcelain", "--untracked-files=all")
    for line in status.splitlines():
        relp = line[3:].split(" -> ")[-1].strip().strip('"')
        try:
            out[relp] = os.stat(os.path.join(top, relp)).st_mtime
        except OSError:
            continue

    return out


def unpushed(cwd: str) -> list[str]:
    log = git(cwd, "log", "--oneline", "@{upstream}..HEAD")

    return log.splitlines() if log else []


# --- hook commands -----------------------------------------------------------------------


def cmd_register(hook: dict) -> None:
    path, rec = own_record(hook)
    text = digest_if_changed(path, rec)
    if text:
        print(text)


def cmd_prompt(hook: dict) -> None:
    path, rec = own_record(hook)
    if not (rec.get("ticket") or {}).get("confirmed"):
        m = TICKET_RE.search(hook.get("prompt") or "")
        if m:
            rec["ticket"] = {"key": m.group(1), "source": "prompt", "confirmed": False}
    text = digest_if_changed(path, rec)
    if text:
        print(text)


def cmd_touch(hook: dict) -> None:
    if hook.get("tool_name") not in EDIT_TOOLS:
        return
    tool_input = hook.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return
    path, rec = own_record(hook)
    record_file(rec, file_path)
    text = digest_if_changed(path, rec)
    if text:
        emit("PostToolUse", additionalContext=text)


def push_reason(cwd: str, me: str) -> str:
    reasons = []
    for r, b in holders(cwd, me, PUSH_BLOCKER):
        reasons.append(f"{r['name']} is pushing to main right now ({b.get('note') or 'no note'})")
    same = [r["name"] for r in neighbours(cwd, me) if r.get("cwd") == cwd]
    if same:
        commits = unpushed(cwd)
        reasons.append(
            f"{', '.join(same)} share(s) this checkout; this push carries every local commit: "
            + ("; ".join(commits) if commits else "none unpushed")
        )

    return " | ".join(reasons)


def stack_reason(cwd: str, me: str) -> str:
    return " | ".join(
        f"{r['name']} ({(r.get('ticket') or {}).get('key') or 'no ticket'}) holds "
        f"{STACK_BLOCKER}: {b.get('note') or 'verifying on the live stack'}"
        for r, b in holders(cwd, me, STACK_BLOCKER)
    )


def cmd_pre_bash(hook: dict) -> None:
    if hook.get("tool_name") != "Bash":
        return
    path, rec = own_record(hook)
    command = (hook.get("tool_input") or {}).get("command", "")
    rec["_snapshot"] = dirty_snapshot(rec["cwd"])
    reason = ""
    if PUSH_RE.search(command):
        reason = push_reason(rec["cwd"], rec["session_id"])
        add_blocker(rec, PUSH_BLOCKER, command.strip()[:80])
        rec["phase"] = "pushing"
    elif is_stack_command(command, rec["cwd"]):
        reason = stack_reason(rec["cwd"], rec["session_id"])
    save(path, rec)
    if reason:
        emit(
            "PreToolUse",
            permissionDecision="ask",
            permissionDecisionReason=f"Another agent session is in the way: {reason}. "
            "Ask the developer, or message that session first.",
        )


def cmd_post_bash(hook: dict) -> None:
    if hook.get("tool_name") != "Bash":
        return
    path, rec = own_record(hook)
    before = rec.pop("_snapshot", {}) or {}
    for relp, mtime in dirty_snapshot(rec["cwd"]).items():
        if before.get(relp) != mtime:
            record_file(rec, os.path.join(toplevel(rec["cwd"]), relp))
    if any(b["type"] == PUSH_BLOCKER for b in rec["blockers"]):
        clear_blocker(rec, PUSH_BLOCKER)
        rec["phase"] = "idle"
    text = digest_if_changed(path, rec)
    if text:
        emit("PostToolUse", additionalContext=text)


def cmd_end(hook: dict) -> None:
    sid = hook.get("session_id", "")
    cwd = hook.get("cwd") or os.getcwd()
    own_path(cwd, sid).unlink(missing_ok=True)


# --- CLI commands ------------------------------------------------------------------------


def cmd_set(hook: dict, args: list[str]) -> None:
    path, rec = own_record(hook)
    it = iter(args)
    for a in it:
        if a == "--ticket":
            rec["ticket"] = {"key": next(it), "source": "implement", "confirmed": True}
        elif a == "--phase":
            rec["phase"] = next(it)
        elif a == "--blocker":
            add_blocker(rec, next(it))
        elif a == "--note" and rec["blockers"]:
            rec["blockers"][-1]["note"] = next(it)
        elif a == "--clear-blocker":
            clear_blocker(rec, next(it))
    save(path, rec)


def cmd_overview(cwd: str, as_json: bool) -> None:
    recs = live_records(cwd)
    if as_json:
        print(json.dumps(recs, indent=1, ensure_ascii=False))
        return
    print(digest(cwd, me="") or f"no live sessions on {repo_name(cwd)}")


def cmd_overlap(cwd: str, me: str) -> None:
    mine = set(load(own_path(cwd, me)).get("files", {}))
    base = git(cwd, "merge-base", "HEAD", "origin/main") or git(cwd, "merge-base", "HEAD", "main")
    if base:
        mine |= set(git(cwd, "diff", "--name-only", base, "HEAD").splitlines())
    mine |= set(dirty_snapshot(cwd))
    hits = []
    for r in neighbours(cwd, me):
        for f in sorted(mine & set(r.get("files", {}))):
            hits.append(f"{f}  <- also {r['name']} ({(r.get('ticket') or {}).get('key') or '—'})")
    print("\n".join(hits) if hits else "no file overlap with other live sessions")


def cmd_check(cwd: str, me: str, kind: str) -> int:
    reason = stack_reason(cwd, me) if kind == STACK_BLOCKER else push_reason(cwd, me)
    if not reason:
        return 0
    print(f"[agents] {reason}", file=sys.stderr)

    return 1


def read_hook_stdin() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        return json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    cwd = os.getcwd()
    me = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if cmd == "overview":
        cmd_overview(cwd, "--json" in rest)
        return 0
    if cmd == "overlap":
        cmd_overlap(cwd, me)
        return 0
    if cmd == "check-stack":
        return cmd_check(cwd, me, STACK_BLOCKER)
    if cmd == "check-push":
        return cmd_check(cwd, me, PUSH_BLOCKER)
    hook = read_hook_stdin()
    if cmd == "set":
        hook.setdefault("session_id", me)
        hook.setdefault("cwd", cwd)
    if not hook.get("session_id"):
        return 0
    handlers = {
        "register": lambda: cmd_register(hook),
        "prompt": lambda: cmd_prompt(hook),
        "touch": lambda: cmd_touch(hook),
        "pre-bash": lambda: cmd_pre_bash(hook),
        "post-bash": lambda: cmd_post_bash(hook),
        "set": lambda: cmd_set(hook, rest),
        "end": lambda: cmd_end(hook),
    }
    handler = handlers.get(cmd)
    if handler is None:
        print(f"board.py: unknown command {cmd}", file=sys.stderr)
        return 0
    handler()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exception as exc:  # noqa: BLE001 - fail open by design, never block a session
        print(f"board.py: {exc}", file=sys.stderr)
        sys.exit(0)
