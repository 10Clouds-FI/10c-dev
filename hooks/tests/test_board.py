"""Tests for the agent awareness board.

Run with:  python3 -m unittest discover -s hooks/tests

The board's problem: a session must see its live neighbours, their ticket, files and blockers,
and a dead session must vanish. Tests exercise that through the same commands the hooks call,
in a temporary Claude home and a temporary git repo.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "board.py"


def load_board(claude_home: Path):
    os.environ["CLAUDE_CONFIG_DIR"] = str(claude_home)
    spec = importlib.util.spec_from_file_location("board", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    return module


class BoardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "claude"
        (self.home / "sessions").mkdir(parents=True)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.sh("git", "init", "-q", "-b", "main")
        self.sh("git", "config", "user.email", "t@t")
        self.sh("git", "config", "user.name", "t")
        (self.repo / "a.txt").write_text("a\n")
        self.sh("git", "add", "a.txt")
        self.sh("git", "commit", "-q", "-m", "init")
        self.board = load_board(self.home)
        self.me = "sid-me"
        self.peer = "sid-peer"
        self.register_session(self.me, "session-me", pid=os.getpid())
        self.register_session(self.peer, "session-peer", pid=os.getpid())

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def sh(self, *args: str) -> str:
        return subprocess.run(
            args, cwd=self.repo, capture_output=True, text=True, check=True
        ).stdout

    def write_config(self, **keys) -> None:
        conf = self.repo / ".claude"
        conf.mkdir(exist_ok=True)
        (conf / "task-flow.json").write_text(json.dumps(keys))

    def register_session(self, sid: str, name: str, pid: int) -> None:
        rec = {"pid": pid, "sessionId": sid, "cwd": str(self.repo), "name": name, "status": "idle"}
        (self.home / "sessions" / f"{name}.json").write_text(json.dumps(rec))

    def run_cmd(self, cmd: str, hook: dict | None = None, *args: str, env: dict | None = None):
        out, err = io.StringIO(), io.StringIO()
        stdin = io.StringIO(json.dumps(hook)) if hook is not None else io.StringIO("")
        stdin.isatty = lambda: False
        patches = {"CLAUDE_CODE_SESSION_ID": self.me, **(env or {})}
        with (
            mock.patch.object(sys, "stdin", stdin),
            mock.patch.dict(os.environ, patches),
            mock.patch("os.getcwd", return_value=str(self.repo)),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            rc = self.board.main([cmd, *args])

        return rc, out.getvalue(), err.getvalue()

    def hook(self, sid: str, **extra) -> dict:
        return {"session_id": sid, "cwd": str(self.repo), **extra}

    # --- the problem the board solves ---------------------------------------------------

    def test_fresh_session_sees_neighbour_ticket_and_files(self) -> None:
        self.run_cmd("prompt", self.hook(self.peer, prompt="work on ABC-192"))
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/x.ts"}),
        )
        _, out, _ = self.run_cmd("register", self.hook(self.me))
        self.assertIn("session-peer", out)
        self.assertIn("ABC-192", out)
        self.assertIn("x.ts", out)
        self.assertIn("same checkout", out)

    def test_digest_is_silent_until_something_changes(self) -> None:
        self.run_cmd("register", self.hook(self.peer))
        self.run_cmd("register", self.hook(self.me))
        _, again, _ = self.run_cmd("prompt", self.hook(self.me, prompt="continue"))
        self.assertEqual(again, "")
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Write", tool_input={"file_path": f"{self.repo}/y.ts"}),
        )
        _, changed, _ = self.run_cmd("prompt", self.hook(self.me, prompt="continue"))
        self.assertIn("y.ts", changed)

    def test_dead_session_disappears(self) -> None:
        self.register_session("sid-dead", "session-dead", pid=2_147_000_000)
        self.run_cmd("register", self.hook("sid-dead"))
        self.run_cmd("register", self.hook(self.peer))
        _, out, _ = self.run_cmd("register", self.hook(self.me))
        self.assertNotIn("session-dead", out)
        self.assertIn("session-peer", out)

    def test_overlap_is_reported(self) -> None:
        for sid in (self.peer, self.me):
            self.run_cmd(
                "touch",
                self.hook(
                    sid, tool_name="Edit", tool_input={"file_path": f"{self.repo}/shared.ts"}
                ),
            )
        _, out, _ = self.run_cmd("prompt", self.hook(self.me, prompt="go"))
        self.assertIn("overlap with you: shared.ts (also edited by session-peer)", out)
        _, cli, _ = self.run_cmd("overlap")
        self.assertIn("shared.ts", cli)

    # --- bash edits -----------------------------------------------------------------------

    def test_files_changed_by_a_bash_command_are_attributed(self) -> None:
        self.run_cmd("pre-bash", self.hook(self.me, tool_name="Bash", tool_input={"command": "ls"}))
        (self.repo / "a.txt").write_text("changed\n")
        (self.repo / "new.py").write_text("x\n")
        self.run_cmd(
            "post-bash", self.hook(self.me, tool_name="Bash", tool_input={"command": "ls"})
        )
        _, out, _ = self.run_cmd("overview", None, "--json")
        files = next(r for r in json.loads(out) if r["session_id"] == self.me)["files"]
        self.assertEqual(set(files), {"a.txt", "new.py"})

    def test_hotspot_edit_sets_a_blocker(self) -> None:
        with mock.patch.object(self.board, "hotspots", return_value=["*.lock"]):
            self.run_cmd(
                "touch",
                self.hook(
                    self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/p.lock"}
                ),
            )
            _, out, _ = self.run_cmd("register", self.hook(self.me))
        self.assertIn('BLOCKER hotspot "p.lock"', out)

    # --- per-repo configuration -----------------------------------------------------------

    def test_hotspots_come_from_task_flow_json(self) -> None:
        self.write_config(hotspots=["*.lock", "docs/*.md"])
        self.assertEqual(self.board.hotspots(str(self.repo)), ["*.lock", "docs/*.md"])
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/p.lock"}),
        )
        _, out, _ = self.run_cmd("register", self.hook(self.me))
        self.assertIn('BLOCKER hotspot "p.lock"', out)

    def test_hotspots_fall_back_to_hotspots_txt(self) -> None:
        conf = self.repo / ".claude"
        conf.mkdir()
        (conf / "hotspots.txt").write_text("# a comment\n\n*.lock\n")
        self.assertEqual(self.board.hotspots(str(self.repo)), ["*.lock"])
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/p.lock"}),
        )
        _, out, _ = self.run_cmd("register", self.hook(self.me))
        self.assertIn('BLOCKER hotspot "p.lock"', out)

    def test_no_config_means_no_hotspots(self) -> None:
        self.assertEqual(self.board.hotspots(str(self.repo)), [])
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/p.lock"}),
        )
        _, out, _ = self.run_cmd("register", self.hook(self.me))
        self.assertNotIn("BLOCKER hotspot", out)

    def test_default_stack_commands_cover_make_and_docker_compose(self) -> None:
        for command in ("make restart", "make start-panel", "docker compose down", "cd x && make nuke"):
            self.assertTrue(
                self.board.is_stack_command(command, str(self.repo)), f"{command!r} should match"
            )
        for command in ("git status", "echo make a start", "npm run start"):
            self.assertFalse(
                self.board.is_stack_command(command, str(self.repo)), f"{command!r} should not match"
            )

    def test_stack_commands_come_from_task_flow_json(self) -> None:
        self.write_config(stackCommands=["just up", "tilt (up|down)"])
        self.assertTrue(self.board.is_stack_command("just up", str(self.repo)))
        self.assertTrue(self.board.is_stack_command("tilt down", str(self.repo)))
        self.assertFalse(self.board.is_stack_command("make recreate", str(self.repo)))
        self.run_cmd(
            "set", self.hook(self.peer), "--blocker", "stack-in-use", "--note", "checking login"
        )
        _, out, _ = self.run_cmd(
            "pre-bash", self.hook(self.me, tool_name="Bash", tool_input={"command": "just up"})
        )
        self.assertIn("checking login", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"])

    def test_a_broken_stack_pattern_is_treated_as_a_literal(self) -> None:
        self.write_config(stackCommands=["make start(("])
        self.assertTrue(self.board.is_stack_command("make start((", str(self.repo)))
        self.assertFalse(self.board.is_stack_command("make stop", str(self.repo)))

    # --- guards ---------------------------------------------------------------------------

    def test_push_from_a_shared_checkout_asks_the_human(self) -> None:
        self.run_cmd("register", self.hook(self.peer))
        _, out, _ = self.run_cmd(
            "pre-bash",
            self.hook(self.me, tool_name="Bash", tool_input={"command": "git push origin main"}),
        )
        decision = json.loads(out)["hookSpecificOutput"]
        self.assertEqual(decision["permissionDecision"], "ask")
        self.assertIn("session-peer", decision["permissionDecisionReason"])
        _, listing, _ = self.run_cmd("overview", None, "--json")
        mine = next(r for r in json.loads(listing) if r["session_id"] == self.me)
        self.assertEqual(mine["blockers"][0]["type"], "pushing-main")
        self.run_cmd(
            "post-bash", self.hook(self.me, tool_name="Bash", tool_input={"command": "git push"})
        )
        _, listing, _ = self.run_cmd("overview", None, "--json")
        mine = next(r for r in json.loads(listing) if r["session_id"] == self.me)
        self.assertEqual(mine["blockers"], [])

    def test_stack_restart_under_a_neighbours_verification_asks(self) -> None:
        self.run_cmd(
            "set", self.hook(self.peer), "--blocker", "stack-in-use", "--note", "checking login"
        )
        _, out, _ = self.run_cmd(
            "pre-bash",
            self.hook(self.me, tool_name="Bash", tool_input={"command": "make recreate"}),
        )
        self.assertIn(
            "checking login", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        )
        rc, _, err = self.run_cmd("check-stack")
        self.assertEqual(rc, 1)
        self.assertIn("session-peer", err)

    def test_harmless_bash_stays_silent(self) -> None:
        self.run_cmd("register", self.hook(self.peer))
        _, out, _ = self.run_cmd(
            "pre-bash", self.hook(self.me, tool_name="Bash", tool_input={"command": "git status"})
        )
        self.assertEqual(out, "")
        rc, _, _ = self.run_cmd("check-stack")
        self.assertEqual(rc, 0)

    def test_mentioning_push_in_a_commit_message_is_not_a_push(self) -> None:
        self.run_cmd("register", self.hook(self.peer))
        cmd = "git commit -F - <<'EOF'\nfix: one session's git push carried another\nEOF"
        _, out, _ = self.run_cmd(
            "pre-bash", self.hook(self.me, tool_name="Bash", tool_input={"command": cmd})
        )
        self.assertEqual(out, "")
        _, out, _ = self.run_cmd(
            "pre-bash",
            self.hook(self.me, tool_name="Bash", tool_input={"command": "cd x && git -C . push"}),
        )
        self.assertIn("ask", out)

    def test_ticket_from_prompt_is_a_guess_until_confirmed(self) -> None:
        self.run_cmd("prompt", self.hook(self.me, prompt="do ABC-1 please"))
        self.run_cmd("prompt", self.hook(self.me, prompt="also look at ABC-2"))
        self.run_cmd("set", self.hook(self.me), "--ticket", "ABC-3", "--phase", "verifying")
        self.run_cmd("prompt", self.hook(self.me, prompt="what about ABC-4"))
        _, out, _ = self.run_cmd("overview", None, "--json")
        mine = next(r for r in json.loads(out) if r["session_id"] == self.me)
        self.assertEqual(mine["ticket"], {"key": "ABC-3", "source": "implement", "confirmed": True})
        self.assertEqual(mine["phase"], "verifying")

    def test_broken_board_file_never_blocks(self) -> None:
        self.run_cmd("register", self.hook(self.me))
        path = self.board.own_path(str(self.repo), self.me)
        path.write_text("{not json")
        rc, _, _ = self.run_cmd("prompt", self.hook(self.me, prompt="go"))
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(path.read_text())["session_id"], self.me)

    # --- pre-edit, auto stack, commit ownership, critic ----------------------------------

    def bash(self, sid: str, command: str, phase: str = "pre-bash"):
        return self.run_cmd(
            phase, self.hook(sid, tool_name="Bash", tool_input={"command": command})
        )

    def decision(self, out: str) -> dict:
        return json.loads(out)["hookSpecificOutput"] if out else {}

    def test_bypass_mode_warns_instead_of_asking(self) -> None:
        self.run_cmd("register", self.hook(self.peer))
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/s.ts"}),
        )
        bypass = {"permission_mode": "bypassPermissions"}
        _, out, _ = self.run_cmd(
            "pre-bash",
            self.hook(self.me, tool_name="Bash", tool_input={"command": "git push"}, **bypass),
        )
        d = self.decision(out)
        self.assertNotIn("permissionDecision", d)
        self.assertIn("session-peer", d["additionalContext"])
        _, out, _ = self.run_cmd(
            "pre-edit",
            self.hook(self.me, tool_name="Edit", tool_input={"file_path": f"{self.repo}/s.ts"}, **bypass),
        )
        d = self.decision(out)
        self.assertNotIn("permissionDecision", d)
        self.assertIn("session-peer", d["additionalContext"])
        _, out, _ = self.run_cmd(
            "pre-bash",
            self.hook(
                self.me,
                tool_name="Bash",
                tool_input={"command": "git push"},
                permission_mode="acceptEdits",
            ),
        )
        self.assertEqual(self.decision(out)["permissionDecision"], "ask")

    def test_editing_a_neighbours_file_asks_once(self) -> None:
        self.run_cmd("set", self.hook(self.peer), "--ticket", "ABC-7")
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/s.ts"}),
        )
        edit = self.hook(self.me, tool_name="Edit", tool_input={"file_path": f"{self.repo}/s.ts"})
        _, out, _ = self.run_cmd("pre-edit", edit)
        d = self.decision(out)
        self.assertEqual(d["permissionDecision"], "ask")
        self.assertIn("session-peer (ABC-7)", d["permissionDecisionReason"])
        _, again, _ = self.run_cmd("pre-edit", edit)
        self.assertEqual(again, "")
        other = self.hook(self.me, tool_name="Edit", tool_input={"file_path": f"{self.repo}/o.ts"})
        self.assertEqual(self.run_cmd("pre-edit", other)[1], "")

    def test_pre_edit_returns_area_rules_once_per_path(self) -> None:
        self.write_config(rules={"src/api": [".claude/rules/backend.md"]})
        edit = self.hook(
            self.me, tool_name="Write", tool_input={"file_path": f"{self.repo}/src/api/x.py"}
        )
        d = self.decision(self.run_cmd("pre-edit", edit)[1])
        self.assertIn(".claude/rules/backend.md", d["additionalContext"])
        self.assertNotIn("permissionDecision", d)
        self.assertEqual(self.run_cmd("pre-edit", edit)[1], "")

    def test_app_start_and_playwright_raise_stack_in_use_and_it_goes_stale(self) -> None:
        self.write_config(app={"start": "make dev"})
        self.bash(self.peer, "make dev")
        _, out, _ = self.bash(self.me, "make recreate")
        self.assertIn("stack-in-use", json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"])
        self.run_cmd("set", self.hook(self.peer), "--phase", "reviewing")
        self.assertEqual(self.bash(self.me, "make recreate")[1], "")
        self.run_cmd(
            "pre-mcp", self.hook(self.peer, tool_name="mcp__playwright__browser_click")
        )
        self.assertNotEqual(self.bash(self.me, "make recreate")[1], "")
        path = self.board.own_path(str(self.repo), self.peer)
        rec = json.loads(path.read_text())
        rec["blockers"][0]["touched"] = "2020-01-01T00:00:00+00:00"
        path.write_text(json.dumps(rec))
        self.assertEqual(self.bash(self.me, "make recreate")[1], "")

    def commit_as(self, sid: str, name: str) -> None:
        self.bash(sid, "git commit")
        (self.repo / name).write_text(name)
        self.sh("git", "add", name)
        self.sh("git", "commit", "-q", "-m", f"add {name}")
        self.bash(sid, "git commit", "post-bash")

    def test_push_names_the_owner_of_foreign_commits(self) -> None:
        bare = Path(self.tmp.name) / "bare.git"
        self.sh("git", "init", "-q", "--bare", str(bare))
        self.sh("git", "remote", "add", "origin", str(bare))
        self.sh("git", "push", "-q", "-u", "origin", "main")
        self.run_cmd("set", self.hook(self.peer), "--ticket", "ABC-9")
        self.commit_as(self.peer, "p.txt")
        self.run_cmd("end", self.hook(self.peer))
        self.register_session(self.peer, "session-peer", pid=2_147_000_000)
        self.commit_as(self.me, "m.txt")
        _, out, _ = self.bash(self.me, "git push")
        reason = self.decision(out)["permissionDecisionReason"]
        self.assertIn("add p.txt", reason)
        self.assertIn("session-peer, ABC-9", reason)
        self.assertNotIn("add m.txt", reason)

    def test_push_range_and_overlap_follow_the_configured_base(self) -> None:
        bare = Path(self.tmp.name) / "bare.git"
        self.sh("git", "init", "-q", "--bare", str(bare))
        self.sh("git", "remote", "add", "up", str(bare))
        self.sh("git", "push", "-q", "up", "main:develop")
        self.write_config(git={"baseBranch": "develop", "remote": "up"})
        self.commit_as(self.me, "m.txt")
        self.assertEqual(self.board.push_range(str(self.repo)), "up/develop..HEAD")
        self.run_cmd(
            "touch",
            self.hook(self.peer, tool_name="Edit", tool_input={"file_path": f"{self.repo}/m.txt"}),
        )
        _, out, _ = self.run_cmd("overlap")
        self.assertIn("m.txt", out)

    def test_own_commits_push_without_asking(self) -> None:
        bare = Path(self.tmp.name) / "bare.git"
        self.sh("git", "init", "-q", "--bare", str(bare))
        self.sh("git", "remote", "add", "origin", str(bare))
        self.sh("git", "push", "-q", "-u", "origin", "main")
        self.commit_as(self.me, "m.txt")
        self.assertEqual(self.bash(self.me, "git push")[1], "")

    def test_risky_push_needs_a_current_critic_pass(self) -> None:
        bare = Path(self.tmp.name) / "bare.git"
        self.sh("git", "init", "-q", "--bare", str(bare))
        self.sh("git", "remote", "add", "origin", str(bare))
        self.sh("git", "push", "-q", "-u", "origin", "main")
        self.write_config(risky=[{"label": "billing", "paths": ["src/billing"]}, "migrations"])
        (self.repo / "src" / "billing").mkdir(parents=True)
        self.commit_as(self.me, "src/billing/x.py")
        reason = self.decision(self.bash(self.me, "git push")[1])["permissionDecisionReason"]
        self.assertIn("critic", reason)
        self.assertIn("src/billing/x.py (billing)", reason)
        self.run_cmd("set", self.hook(self.me), "--critic", "pass")
        self.assertEqual(self.bash(self.me, "git push")[1], "")
        self.run_cmd(
            "touch",
            self.hook(self.me, tool_name="Edit", tool_input={"file_path": f"{self.repo}/a.txt"}),
        )
        self.assertIn("stale", self.bash(self.me, "git push")[1])
        _, ov, _ = self.run_cmd("overview", None, "--json")
        self.assertEqual(json.loads(ov)[0]["critic"]["verdict"], "PASS")

    def test_default_risky_labels_match_common_paths(self) -> None:
        cwd = str(self.repo)
        self.assertEqual(self.board.risky_hit("app/migrations/0002_x.py", cwd), "migrations")
        self.assertEqual(self.board.risky_hit("core/tenant/models.py", cwd), "tenant isolation")
        self.assertEqual(self.board.risky_hit("web/Button.tsx", cwd), "")


if __name__ == "__main__":
    unittest.main()
