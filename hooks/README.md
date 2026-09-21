# Agent awareness board

Several Claude Code sessions often run on one machine against one repo — sometimes against one
checkout. Each of them normally has no idea the others exist, so two sessions edit the same file,
one restarts the shared local stack while another is verifying on it, and a push from either
carries the other's half-finished commits.

The board fixes that. Every session writes a small JSON record about itself, and reads its
neighbours' records back as a short digest: who is here, which ticket, which phase, which branch,
which files they touched last, and what they are holding.

## How it works

One JSON file per live session under `~/.claude/10c-dev/board/<repo-id>/<session-id>.json`
(`CLAUDE_CONFIG_DIR` is respected), written only by that session's own hooks. `<repo-id>` is a
hash of the git common dir, so worktrees of one repo share a board.

Liveness comes from Claude Code's own session registry (`~/.claude/sessions/*.json`) plus a pid
check — there is no TTL to tune, and a crashed session's record is pruned the next time anyone
reads the board.

## The six hooks

| Event | Command | What it does |
|---|---|---|
| `SessionStart` | `board.py register` | creates the record, prints the neighbour digest |
| `UserPromptSubmit` | `board.py prompt` | guesses the ticket key from the prompt; prints the digest if it changed |
| `PreToolUse` (Bash) | `board.py pre-bash` | snapshots dirty files; asks for permission before `git push` or a stack command when a neighbour is in the way |
| `PostToolUse` (Edit\|Write\|MultiEdit\|NotebookEdit) | `board.py touch` | records the file; a hotspot raises a blocker |
| `PostToolUse` (Bash) | `board.py post-bash` | attributes the files the command changed; feeds the digest back as `additionalContext` |
| `SessionEnd` | `board.py end` | removes the record |

The digest is printed only when it has *changed* since this session last saw it, so a quiet
machine stays quiet.

## CLI

Usable by hand, by a skill, or from a Makefile / task runner:

```
board.py overview [--json]     live sessions on this repo
board.py overlap               files this session and a neighbour both touch
board.py check-stack           exit 1 + explanation when a neighbour holds `stack-in-use`
board.py check-push            exit 1 + explanation when a neighbour holds `pushing-main`
board.py set --ticket KEY | --phase P | --blocker T [--note N] | --clear-blocker T
```

The session is taken from `$CLAUDE_CODE_SESSION_ID` where one is needed. A typical guard on a
stack-restarting target:

```make
start:
	@python3 board.py check-stack || { printf "continue anyway? [y/N] "; read a; [ "$$a" = y ] || exit 1; }
```

## Configuration — `<repo>/.claude/task-flow.json`

Two keys, both optional:

- **`hotspots`** — array of fnmatch globs relative to the repo root, naming files where two
  parallel changes reliably collide (lockfiles, migrations, a shared API router, i18n bundles).
  Editing one puts a `hotspot` blocker on the session so neighbours see it in their digest.
  Note that in fnmatch a `*` matches `/` too. Falls back to `<repo>/.claude/hotspots.txt` (one glob per line, `#` comments) when the key is
  absent; an empty list when neither exists.

  ```json
  { "hotspots": ["pnpm-lock.yaml", "*/migrations/*.py", "docker-compose*.yml"] }
  ```

- **`stackCommands`** — array of regexes or plain command prefixes that mean "this restarts the
  shared local stack". Each entry is matched at the start of a shell command (also after `;`,
  `&&`, `|` or `(` ), so a mention inside a commit message is not a match. An entry that is not a
  valid regex is matched literally.

  ```json
  { "stackCommands": ["make start", "make stop", "docker compose down", "tilt (up|down)"] }
  ```

  Default: `make (start|stop|restart|recreate|down|nuke)` and `docker compose (up|down|restart)`.

## Fails open, always

The board is an advisory layer, never a gate. Any error — unreadable record, missing git, broken
JSON, absent config — prints a single line to stderr and exits 0, so a broken board can never
block a session. The only thing it ever escalates is a `permissionDecision: "ask"` on a push or a
stack restart while a neighbour holds the matching blocker, which the developer answers.

Requires `python3` (3.10 or newer). No third-party dependencies.

## Tests

```
python3 -m unittest discover -s hooks/tests
```
