#!/usr/bin/env python3
"""Agent awareness board: parallel Claude Code sessions on one machine see each other.

One JSON file per live Claude Code session under ~/.claude/10c-dev/board/<repo-id>/, written
only by that session's hooks. Liveness comes from Claude Code's own registry in
~/.claude/sessions/<pid>.json plus a pid check, so there is no TTL to tune.

Hook commands (stdin = the hook's JSON), wired in hooks/hooks.json:

    register    SessionStart      create the record, print the neighbour digest
    prompt      UserPromptSubmit  guess the ticket key from the prompt, print the digest if changed
    pre-edit    PreToolUse Edit/Write/...  "ask" before editing a file a live neighbour is
                                  editing; once per path, the area rule files to read first
    touch       PostToolUse       Edit/Write/...: record the file; hotspot -> blocker
    pre-mcp     PreToolUse mcp__*playwright*  raise `stack-in-use` (browser use = local stack use)
    pre-bash    PreToolUse Bash   snapshot dirty files and HEAD; raise `stack-in-use` on the app
                                  start / a stack command; "ask" before git push / a stack command
                                  when a neighbour is in the way, before a push that carries
                                  another session's commits, and before a push that touches a
                                  risky area without a critic PASS

In bypassPermissions mode every "ask" becomes a warning in additionalContext instead.
    post-bash   PostToolUse Bash  attribute files the command changed; record the SHAs a
                                  git commit created; digest as additionalContext
    end         SessionEnd        remove the record

CLI (session from $CLAUDE_CODE_SESSION_ID when needed):

    overview [--json]                 live sessions on this repo
    overlap                           files this session and a neighbour both touch
    check-stack | check-push          exit 1 and explain when a neighbour holds the blocker
    set --ticket K | --phase P | --blocker T [--note N] | --clear-blocker T | --critic PASS|FAIL

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
    git            `baseBranch` (default `main`) and `remote` (default `origin`): the range a
                   push carries and the base `overlap` diffs against.
    app.start      the command that brings the local stack up; running it raises `stack-in-use`.
    rules          map of path prefix -> rule files; the first edit of a path in a session gets
                   the matching files back as context ("read these before editing").
    risky          array of risky area labels (default: tenant isolation, authz, migrations,
                   pipelines, chat gateway) or globs/path prefixes. A push whose diff touches
                   one needs a recorded critic PASS newer than the last edit, or it asks.

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
# An auto-raised `stack-in-use` goes stale after this long without stack activity.
STACK_IDLE_SECONDS = 900
COMMIT_RE = re.compile(r"(?:^|[;&|(]\s*)git\b[^;&|\n]*?\b(?:commit|cherry-pick|revert|am)\b", re.MULTILINE)
MAX_COMMITS_LEDGER = 2000
DEFAULT_RISKY = ["tenant isolation", "authz", "migrations", "pipelines", "chat gateway"]
# Label -> path globs, so the PDF's plain-language areas work with no per-repo setup.
RISKY_GLOBS = {
    "tenant": ["*tenant*"],
    "authz": ["*authz*", "*auth/*", "*authentication*", "*permission*", "*rbac*"],
    "auth": ["*authz*", "*auth/*", "*authentication*", "*permission*", "*rbac*"],
    "migration": ["*migration*"],
    "pipeline": ["*pipeline*", ".github/workflows/*", ".gitlab-ci*", "*.azure-pipelines*"],
    "gateway": ["*gateway*"],
}


def now() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="milliseconds")


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


def blocker_stale(b: dict) -> bool:
    """An auto-raised blocker nobody has refreshed for STACK_IDLE_SECONDS."""
    if not b.get("auto"):
        return False
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(b.get("touched") or b["since"])
    except (KeyError, ValueError):
        return False

    return age.total_seconds() > STACK_IDLE_SECONDS


def holders(cwd: str, me: str, kind: str) -> list[tuple[dict, dict]]:
    return [
        (r, b)
        for r in neighbours(cwd, me)
        for b in r.get("blockers", [])
        if b["type"] == kind and not blocker_stale(b)
    ]


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


def app_start(cwd: str) -> str:
    app = config(cwd).get("app")

    return str(app.get("start") or "").strip() if isinstance(app, dict) else ""


def is_app_start(command: str, cwd: str) -> bool:
    start = app_start(cwd)
    if not start:
        return False

    return re.search(STACK_PREFIX + re.escape(start), command, re.MULTILINE) is not None


def matching_rules(path: str, cwd: str) -> list[str]:
    rules = config(cwd).get("rules")
    if not isinstance(rules, dict):
        return []
    found: list[str] = []
    for prefix, files in rules.items():
        key = str(prefix).rstrip("/")
        hit = path == key or path.startswith(key + "/") or fnmatch.fnmatch(path, str(prefix))
        if hit and isinstance(files, list):
            found.extend(str(f) for f in files if str(f) not in found)

    return found


def risky_entries(cwd: str) -> list[tuple[str, list[str]]]:
    """(label, explicit path globs) pairs. An entry is a label, a glob, or {label, paths[]}."""
    configured = config(cwd).get("risky")
    if not isinstance(configured, list):
        return [(label, []) for label in DEFAULT_RISKY]
    out: list[tuple[str, list[str]]] = []
    for e in configured:
        if isinstance(e, dict):
            label = str(e.get("label") or "").strip()
            paths = [str(x).strip() for x in e.get("paths") or [] if str(x).strip()]
            if label or paths:
                out.append((label or paths[0], paths))
        elif str(e).strip():
            text = str(e).strip()
            out.append((text, [text] if re.search(r"[/*.]", text) else []))

    return out


def path_matches(path: str, pattern: str) -> bool:
    key = pattern.rstrip("/")

    return path == key or path.startswith(key + "/") or fnmatch.fnmatch(path, pattern)


def risky_hit(path: str, cwd: str) -> str:
    """The risky label that `path` falls under, or ''."""
    low = path.lower()
    for label, paths in risky_entries(cwd):
        if paths:
            if any(path_matches(path, g) for g in paths):
                return label
            continue
        words = re.findall(r"[a-z]+", label.lower())
        globs = [g for w in words for k, gs in RISKY_GLOBS.items() if w.startswith(k) for g in gs]
        globs = globs or [f"*{w}*" for w in words if len(w) > 3]
        if any(fnmatch.fnmatch(low, g) for g in globs):
            return label

    return ""


# --- board record helpers -------------------------------------------------------------------


def add_blocker(rec: dict, kind: str, note: str = "", auto: bool = False) -> None:
    for b in rec["blockers"]:
        if b["type"] == kind:
            if note:
                b["note"] = note
            if b.get("auto"):
                b["touched"] = now()

            return
    b = {"type": kind, "since": now()}
    if note:
        b["note"] = note
    if auto:
        b["auto"] = True
        b["touched"] = b["since"]
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
        crit = (r.get("critic") or {}).get("verdict")
        if crit:
            blockers = f"critic {crit}  {blockers}"
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


# Set from the hook's permission_mode. A developer who chose bypassPermissions opted out of
# prompts, so an "ask" becomes a warning in the agent's context instead of a dialog.
BYPASS = False


def emit(event: str, **fields: str) -> None:
    if BYPASS and fields.get("permissionDecision") == "ask":
        del fields["permissionDecision"]
        reason = fields.pop("permissionDecisionReason", "")
        fields["additionalContext"] = " ".join(
            t for t in (reason, fields.get("additionalContext", "")) if t
        )
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


def head_sha(cwd: str) -> str:
    return git(cwd, "rev-parse", "HEAD")


def ledger_path(cwd: str) -> Path:
    return board_dir(cwd) / "commits.ledger"


def ledger(cwd: str) -> dict:
    data = load(ledger_path(cwd))

    return data if isinstance(data, dict) else {}


def record_commits(rec: dict, before: str) -> None:
    """Attribute the commits a git command created (before..HEAD) to this session."""
    cwd = rec["cwd"]
    head = head_sha(cwd)
    if not head or head == before:
        return
    shas = git(cwd, "rev-list", "--max-count=50", f"{before}..{head}" if before else head)
    new = shas.splitlines() if shas else []
    if not new:
        return
    book = ledger(cwd)
    owner = {
        "session": rec["session_id"],
        "name": rec.get("name", ""),
        "ticket": (rec.get("ticket") or {}).get("key") or "",
    }
    for sha in new:
        book[sha] = owner
    while len(book) > MAX_COMMITS_LEDGER:
        book.pop(next(iter(book)))
    path = ledger_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(book))
    tmp.replace(path)


def base_refs(cwd: str) -> tuple[str, str]:
    """The remote-tracking base and the local base, from `git.remote` / `git.baseBranch`."""
    git_cfg = config(cwd).get("git")
    git_cfg = git_cfg if isinstance(git_cfg, dict) else {}
    base = str(git_cfg.get("baseBranch") or "main").strip() or "main"
    remote = str(git_cfg.get("remote") or "origin").strip() or "origin"

    return f"{remote}/{base}", base


def push_range(cwd: str) -> str:
    if git(cwd, "rev-parse", "--verify", "-q", "@{upstream}"):
        return "@{upstream}..HEAD"
    for base in base_refs(cwd):
        if git(cwd, "rev-parse", "--verify", "-q", base):
            return f"{base}..HEAD"

    return ""


def foreign_commits_reason(cwd: str, me: str) -> str:
    rng = push_range(cwd)
    if not rng:
        return ""
    book = ledger(cwd)
    lines = []
    for ln in git(cwd, "log", "--format=%H %h %s", rng).splitlines():
        full, short, subject = ln.split(" ", 2)
        owner = book.get(full)
        if not owner or owner.get("session") == me:
            continue
        who = owner.get("name") or owner.get("session", "")[:8]
        ticket = owner.get("ticket")
        lines.append(f"{short} {subject[:50]} (made by {who}" + (f", {ticket}" if ticket else "") + ")")

    return ("this push carries commits that belong to another session: " + "; ".join(lines)) if lines else ""


def critic_reason(rec: dict) -> str:
    cwd = rec["cwd"]
    rng = push_range(cwd)
    if not rng:
        return ""
    hits = sorted(
        {
            f"{f} ({label})"
            for f in git(cwd, "diff", "--name-only", rng).splitlines()
            if (label := risky_hit(f, cwd))
        }
    )
    if not hits:
        return ""
    critic = rec.get("critic") or {}
    last_edit = max(rec.get("files", {}).values(), default="")
    if critic.get("verdict") == "PASS" and critic.get("at", "") >= last_edit:
        return ""
    state = (
        f"critic {critic['verdict']} is stale (files edited since)"
        if critic.get("verdict") == "PASS"
        else f"critic verdict is {critic.get('verdict', 'missing')}"
    )

    return (
        "risky change without a current critic PASS ("
        + state
        + "): "
        + ", ".join(hits[:4])
        + ". Run the critic, then `board.py set --critic PASS`"
    )


def stack_touch(rec: dict, note: str) -> None:
    add_blocker(rec, STACK_BLOCKER, note, auto=True)
    for b in rec["blockers"]:
        if b["type"] == STACK_BLOCKER and b.get("auto"):
            b["touched"] = now()


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


def cmd_pre_edit(hook: dict) -> None:
    if hook.get("tool_name") not in EDIT_TOOLS:
        return
    tool_input = hook.get("tool_input") or {}
    file_path = tool_input.get("file_path") or tool_input.get("notebook_path")
    if not file_path:
        return
    path, rec = own_record(hook)
    relp = rel(file_path, rec["cwd"])
    fields: dict[str, str] = {}
    warned = rec.setdefault("overlap_warned", [])
    if relp not in warned:
        owners = [
            f"{r['name']} ({(r.get('ticket') or {}).get('key') or 'no ticket'})"
            for r in neighbours(rec["cwd"], rec["session_id"])
            if relp in r.get("files", {})
        ]
        if owners:
            warned.append(relp)
            fields["permissionDecision"] = "ask"
            fields["permissionDecisionReason"] = (
                f"{relp} is being edited by {', '.join(owners)}. "
                "Message that session or ask the developer before editing it too."
            )
    shown = rec.setdefault("rules_shown", [])
    if relp not in shown:
        rules = matching_rules(relp, rec["cwd"])
        if rules:
            shown.append(relp)
            fields["additionalContext"] = (
                f"Area rules for {relp}: read {', '.join(rules)} before this edit, if you "
                "have not already."
            )
    save(path, rec)
    if fields:
        emit("PreToolUse", **fields)


def cmd_pre_mcp(hook: dict) -> None:
    if "playwright" not in str(hook.get("tool_name", "")).lower():
        return
    path, rec = own_record(hook)
    stack_touch(rec, "driving the app in the browser")
    save(path, rec)


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
    rec["_head"] = head_sha(rec["cwd"]) if COMMIT_RE.search(command) else ""
    reason = ""
    if is_app_start(command, rec["cwd"]):
        stack_touch(rec, "app started, verifying on the live stack")
    if PUSH_RE.search(command):
        reason = " | ".join(
            r
            for r in (
                push_reason(rec["cwd"], rec["session_id"]),
                foreign_commits_reason(rec["cwd"], rec["session_id"]),
                critic_reason(rec),
            )
            if r
        )
        add_blocker(rec, PUSH_BLOCKER, command.strip()[:80])
        rec["phase"] = "pushing"
    elif is_stack_command(command, rec["cwd"]):
        reason = stack_reason(rec["cwd"], rec["session_id"])
        if not re.search(r"\b(?:stop|down|nuke)\b", command):
            stack_touch(rec, "restarted the local stack")
    save(path, rec)
    if reason:
        emit(
            "PreToolUse",
            permissionDecision="ask",
            permissionDecisionReason=f"Before this push or restart: {reason}. "
            "Ask the developer, or message that session first.",
        )


def cmd_post_bash(hook: dict) -> None:
    if hook.get("tool_name") != "Bash":
        return
    path, rec = own_record(hook)
    before = rec.pop("_snapshot", {}) or {}
    head_before = rec.pop("_head", "")
    if head_before:
        record_commits(rec, head_before)
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
            if rec["phase"] != "verifying":
                rec["blockers"] = [
                    b for b in rec["blockers"] if not (b["type"] == STACK_BLOCKER and b.get("auto"))
                ]
        elif a == "--critic":
            verdict = next(it).upper()
            if verdict in ("PASS", "FAIL"):
                rec["critic"] = {"verdict": verdict, "at": now(), "head": head_sha(rec["cwd"])}
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
    remote_base, local_base = base_refs(cwd)
    base = git(cwd, "merge-base", "HEAD", remote_base) or git(cwd, "merge-base", "HEAD", local_base)
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
    global BYPASS
    BYPASS = hook.get("permission_mode") == "bypassPermissions"
    handlers = {
        "register": lambda: cmd_register(hook),
        "prompt": lambda: cmd_prompt(hook),
        "pre-edit": lambda: cmd_pre_edit(hook),
        "pre-mcp": lambda: cmd_pre_mcp(hook),
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
