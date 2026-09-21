---
name: implement
description: "Drives the full build cycle for a task. Moves the tracker ticket to In Progress (for a real key), runs the `coding` skill's phases (rung, interview, spec, minimal build, tests at R2+, proof on the live app, self-review with `code-review`), offers an adversarial critic, closes with `cleanup` and a project-model update, then offers to commit and push; the ticket status follows the code (In Progress locally, In Review once on the shared branch, Done once checked in production). Accepts a real ticket key of ANY project (e.g. `ABC-123`, `PROJ-42`), or a synthetic local key (e.g. `LOCAL-20260729-1430`) for ad-hoc work with no ticket."
metadata:
  version: 1.0.0
  title_en: Implement a task end to end
  summary_en: The build cycle — ticket, rung, interview, spec, minimal build, verification, self-review, cleanup, commit.
  category: [development]
allowed-tools: Bash, Read, Edit, Write, Grep, Glob, mcp__atlassian__*, mcp__playwright__*
---

# The build cycle

This skill drives one task from ticket to pushed code. Everything project-specific comes
from the consuming repo's `.claude/task-flow.json` — read it first; if it is missing, say so
and fall back to the defaults named below.

## The repo config

Read `.claude/task-flow.json` at the start of the session. Fields used here:

| Field | Used for |
|---|---|
| `tracker` | `"jira"` → do the ticket steps; `"none"` → skip every ticket step (the `LOCAL-` path) |
| `jira.site`, `jira.projectKey`, `jira.board`, `jira.cloudId` | tracker access |
| `statusMap`, `transitionIds` | the names/ids this board uses for To Do / In Progress / In Review / Done |
| `git.baseBranch`, `git.remote`, `git.mode`, `git.branchPrefix` | where the code goes and how (Step 7) |
| `verify.commands`, `verify.byArea` | the validation gate, and the extra commands for a touched area |
| `app.start`, `app.urls` | how to bring the app up and where to look at it (Step 3) |
| `rules` | which rule files to read before touching which paths (Step 2) |
| `slack.projectChannel`, `slack.workspace` | the optional heads-up in Step 7 |
| `reporting.language`, `reporting.commentStyle` | how ticket comments are written |
| `notes` | board quirks the team already learned |

If the file does not exist, treat it as `tracker: "none"`, `git.baseBranch: "main"`,
`git.mode: "push-to-main"`, no verify commands, and say in one line that the repo has no
`task-flow.json` so you are guessing the gate from `package.json` / `Makefile` / CI config.

## Tracker access

Two paths, in this order:

1. **The `atlassian` MCP server** (`mcp__atlassian__*`), declared in the plugin's `.mcp.json`
   with OAuth per user. Every call needs a `cloudId`: take it from `jira.cloudId` in the config,
   or fetch it once per session with `mcp__atlassian__getAccessibleAtlassianResources` and reuse it.
2. **The plugin's `jira` skill scripts**, when the MCP server is not connected:

   ```
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/get_issue.py KEY
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/transition.py KEY --to "In Progress"
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/assign.py KEY <email>
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/comment.py KEY --body "..."
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jql_search.py 'project = ABC AND status = "In Progress"'
   ```

   They read the site from `.claude/task-flow.json` (`jira.site`) or the `JIRA_SITE` env var,
   and credentials from `JIRA_EMAIL` / `JIRA_API_TOKEN` or
   `$CLAUDE_PLUGIN_DATA/jira/credentials.json`. First run:
   `${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/setup.py`.

**Never stop because the MCP server is not authenticated** — fall through to the scripts. Only
if both paths fail do you say so and offer the `LOCAL-` path rather than guessing ticket state.

**The project is whatever the ticket key prefix says.** Derive it from the key, never hardcode
a project. If the user names a different project than the key implies, follow the user.

## Preconditions

- A task key has been identified: a real tracker key or a synthetic `LOCAL-` key.
- An execution mode has been chosen: **Direct** (small), **Feature-dev** (medium/large, hands
  off to a feature-development plugin), or **Plan-mode**. If the user has not picked one, ask.
- The user has explicitly confirmed proceeding.

If the user gave only a freeform request with no key and no mode, ask which they want (and
whether to create a ticket first) rather than guessing.

### Key types

- **Real ticket key** (matches `^[A-Z]+-\d+$`, e.g. `ABC-123`): do all tracker transitions
  against the key's own project.
- **Synthetic local key** (starts with `LOCAL-`), or `tracker: "none"` in the config: **skip
  every tracker call**. Still implement, still verify, still summarise.

When a step says "transition the ticket", read it as a no-op for those.

## Before Step 1: start from the current base branch

Other people and other sessions push to the base branch all day, and that branch is what the
shared environment runs. Code written on a stale checkout verifies against a world that no
longer exists. So, first thing:

```bash
git fetch <remote>
git status --short
git rev-list --left-right --count HEAD...<remote>/<baseBranch>
```

- Behind and the tree is clean: `git pull --ff-only` and continue.
- Behind and the tree is dirty, or the branch has diverged: stop and tell the developer what
  you see (which files are modified, how many commits behind). They decide: commit, stash by
  name, or work on a fresh worktree. Never stash, reset or merge on their behalf.
- In a worktree on a feature branch: the same check against the base branch, and say how far
  behind it is; rebasing is the developer's call.

Allowed git here: `fetch`, `status`, `log`, `diff`, `rev-list`, `worktree list` and a
fast-forward `pull` on a clean tree. Nothing that rewrites history. Commit and push come only
in Step 7, after the developer's yes.

## Before Step 1: read the room

Other Claude Code sessions may be working in this repo on this machine right now. Their digest
arrives in your context automatically from the plugin's hooks, but before the ticket is opened
look deliberately:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py overview
python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py overlap
```

- `overview` lists the live sessions: name, ticket, phase, branch, files, blockers.
- `overlap` lists files this task already touches (working tree, commits since the base branch)
  that a neighbour is also editing. **Non-empty overlap is reported to the developer before the
  first edit**, with the neighbour's name, and you offer three options: continue, message that
  session, or wait. Never edit an overlapping file without the developer's word.
- A neighbour in the **same checkout** means a push from either session carries the other's
  commits. Say so when you get to Step 7.
- Real ticket key: also glance at the other **In Progress** tickets of the project (JQL
  `project = <PROJECT> AND status = "In Progress" AND assignee != currentUser()`), one line
  each, so the developer knows whose work is nearby on other machines.

Report the three results in one short block, then continue.

## Before Step 1: read the project model

If `docs/PROJECT_MODEL.md` exists, read it now, before the ticket is even opened. Use it to
weigh the task: a change near a `core` capability gets the interview, tests and the critic; a
change to something marked `legacy-keep` or `dead` gets the question "should this exist at all"
before any code. If the file does not exist, say so in one line and continue.

## Steps

### 1. Move the ticket to In Progress

**Real ticket key only** (skip for `LOCAL-` and `tracker: "none"`):

- Let `PROJECT` be the key prefix.
- If `transitionIds.in_progress` is set in the config, use it directly. Otherwise resolve the
  transition by name (`statusMap.in_progress`, matched case-insensitively) — via
  `mcp__atlassian__getTransitionsForJiraIssue`, or `transition.py KEY --to "<name>"`.
- If no matching transition exists (already in progress, or the workflow differs), continue
  silently. Do not error out.
- Tell the board which ticket this session owns, for any key type:
  `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py set --ticket <KEY> --phase designing`.
  The hooks track files and phases from here on; you only set the phase at the marked points.
- **Sprint check (best effort, not fatal):** fetch the ticket and look for a sprint custom
  field (the id varies by project, so inspect the issue fields). If the ticket has no active
  sprint, look for one with `project = <PROJECT> AND sprint in openSprints()` and, if found,
  move the ticket in. If the project has no sprint field or no open sprint, **skip silently**.

### 2. Implement by mode

**The `coding` skill runs inside this step and is not optional.** Load it before the first
edit and follow its phases in order; this skill only says where they sit in the cycle:

| `coding` phase | Where in this skill |
|---|---|
| 1 Say the rung out loud (R0 probe / R1 PoC / R2 MVP / R3 hardened) | here, before any edit; the mode says how much ceremony, the rung says how finished |
| 2 Interview, one question per message | here, before designing; the ticket is input to the interview, not a substitute for it |
| 3 Tiny spec in chat (goal, done-when from the user's side, out of scope, plan) | here, in the conversation, never as a file in the repo |
| 4 Build the smallest thing, surgically | here |
| 5 Tests at R2+, at the level of the problem a module solves; a bug gets a reproducing test first | here; run `verify.commands` plus the `verify.byArea` set for the touched area |
| 6 Prove it on the artifact a human uses | Step 3 below |
| 7 Review your own diff with `code-review` (R2+) | Step 3b below |
| 8 Closing reflection with `cleanup` | Step 6 below |
| 9 Project model | read `docs/PROJECT_MODEL.md` before designing; update it in Step 6 |

The rung is a one-way ratchet: step up only after saying so and getting agreement, never
quietly down.

- **Direct mode:** make the change yourself with `Edit` and `Write`. Keep diffs minimal.
- **Feature-dev mode:** invoke the repo's feature-development plugin and follow its workflow,
  staying human-in-the-loop at its checkpoints. If no such plugin is installed, say so and
  offer Plan-mode instead.
- **Plan-mode:** enter plan mode and do not edit files until the user approves the plan.

Regardless of mode, surface changes incrementally. Do not batch ten files of edits before the
first check-in.

**Load the rules for what you are touching before writing code.** They are mandatory, not
advisory:

- Read the `rules` map in `.claude/task-flow.json`: every entry whose path prefix matches a
  file you are about to touch names the rule files to read first.
- If the repo has no `rules` map, read every `.claude/rules/*.md` whose name matches the area
  you are in, plus the repo's `CLAUDE.md` (and `CONTRIBUTING.md` / `docs/gotchas.md` if
  present).
- A rule that seems wrong is surfaced to the developer before you deviate, never silently
  ignored.

### 3. Verify against the live app (if UI or behaviour was touched)

**Hold the stack while you verify.** Before the first browser or stack interaction:
`python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py set --phase verifying --blocker stack-in-use --note "<what>"`.
Neighbours are then asked before they restart or rebuild the local stack. Clear it as soon as
verification ends:
`python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py set --clear-blocker stack-in-use --phase reviewing`.
If a neighbour holds `stack-in-use` when you need the stack, do not restart or migrate it; tell
the developer who holds it and why, and wait or message that session.

> **Browser verification:** the `playwright` MCP server is declared in the plugin's `.mcp.json`,
> so you can drive the browser directly with `mcp__playwright__*`. If those tools are not
> loaded, start a fresh session. The built-in **`run`** skill is a good alternative for
> starting the service, especially for non-UI work.

- Bring the app up with `app.start` from the config if it is not already running.
- If the change affected the UI, exercise it at the relevant address from `app.urls` and run a
  short self-correction loop on failures.
- If the change is purely backend or non-UI (a migration, an endpoint, a background job),
  exercise it directly (tests, an API call, worker logs) and say so explicitly in the next
  step's brief.
- **If the config lists area-specific verification** (`verify.byArea`) for a path you touched,
  run it — a command that CI skips is exactly the one that bites after the push.

### 3b. Review your own diff (R2 and above)

Load the `code-review` skill and run it over the whole diff of this task: the current branch
against the base branch, uncommitted changes included. Fix every **blocker** and **major**
before Step 4. List minors and nits for the user; do not silently widen the scope to fix them.
A finding about pre-existing code goes into Step 6's cleanup list, not into a drive-by fix.
Skip at R0 and R1 unless the user asks.

### 4. Prepare a testing brief

The ticket already records *what* was done. Prepare a brief in the conversation: this is what
you hand to the critic in Step 5, and what the user can read directly.

- **Ticket or topic:** `<KEY>: <summary>`
- **Scenario:** ordered steps to verify the work, including the exact inputs and prompts that
  worked in Step 3
- **Expected outcomes:** per step, what the UI, API or worker should do
- **Regression watch-list:** areas this change could plausibly break

Keep the brief in the conversation. It does not need to be written to disk unless the user asks.

**Optional: capture learning.** If the session produced a non-obvious gotcha, offer to add it
to the repo's gotchas doc so the next developer does not rediscover it. Offer, never auto-write.

### 5. Run critique

After Step 4, ask the user: "Run the adversarial critic now, or go straight to cleanup and
commit?" Wait for the answer.

**Branch A, user says run critique.**

- Invoke the critic agent with the ticket key and the URL where the app is running. For a
  `LOCAL-` key pass the Step 4 brief in the prompt; the critic uses it instead of a ticket.
- Do not edit code or restart containers while it runs; its result is about the stack as it
  was when it started.
- It runs in an isolated context, reads the ticket itself, builds its own attack plan, and
  returns PASS or FAIL.
- If FAIL: surface the report, ask whether to fix and re-run or continue as is.
- If PASS: go to Step 6.

**Branch B, user skips the critic.** Go to Step 6.

Run the critic **once**, at the end. Looping it produces endless nitpicks. It earns its keep on
backend, data-isolation and security-sensitive work more than on visual frontend tweaks.

### 6. Close: cleanup and the project model

Runs after Step 5, at R1 and above, before anything is committed.

- Load `cleanup` and run it over the whole task's diff: delete your own orphans (unused
  imports, helpers, fixtures, flags your change made unreachable); propose, with grep evidence,
  the pre-existing code your change made pointless; mention unrelated rot in one sentence and
  leave it alone. A proposed removal is handed to the developer as a list; an accepted one
  lands in its own commit, never inside the feature commit.
- If `docs/PROJECT_MODEL.md` exists, update it in the same session: what this change added or
  altered in an existing capability you write yourself; an area missing from the model gets an
  entry with status `unknown` and one sentence; a status change of someone else's capability
  (say, to `dead`) is proposed to the area owner, not written. A stale model is worse than none.
  If it does not exist and the task was R2 or higher, offer to build it with `project-model` (a
  one-time interview with the team, in English).

### 7. Offer to commit and push; the ticket status follows the code

When the code works locally, the diff is reviewed and cleanup is done, **offer to commit and
push.** Do not wait to be asked, and do not do it unasked: one question, "Commit and push to
`<branch>`?", with the proposed commit message in it.

- Before the push, `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py check-push`: a non-zero exit
  names a neighbour that is pushing right now or shares this checkout, and lists the local
  commits your push would carry. Stop and show that to the developer; push only on their word.
  The `PreToolUse` hook asks the same question mechanically, so do not route around it.
- On yes: `git add` the files of this task only (never `-A`), commit in the repo's format
  (`<type>(<scope>): <subject>` unless the repo says otherwise), English, imperative, no emoji,
  one coherent change per commit (cleanup separately, see Step 6). The ticket key goes in the
  commit body, along with the Step 3b summary: verdict, counts per severity, one line per
  blocker/major and what was done about it.
- **How the code reaches the shared branch depends on `git.mode`:**
  - `push-to-main` — commit on `git.baseBranch` and `git push` straight to it. The team does
    not open pull requests in this mode; never propose one.
  - `pr` — work on a branch named `<git.branchPrefix><KEY>-<slug>`, push it, then open a pull
    request with `gh pr create`, the ticket key in the title, and the testing brief in the body.
- Read the push result: a rejected push means someone else pushed first; fetch and tell the
  developer, do not force anything.
- On no: finish with a one-line summary and the testing brief from Step 4. Nothing else.

The ticket's status says where the code IS, never how the conversation went. The mapping is
fixed and this skill never moves a ticket ahead of it:

| Where the code is | Status | Transition |
|---|---|---|
| on a branch, in a worktree, uncommitted | In Progress | set in Step 1 |
| pushed to the base branch (or the PR is open, in `pr` mode), so it is on the shared environment | In Review | `transitionIds.in_review` / `statusMap.in_review` |
| promoted to production and checked there by a human | Done | `transitionIds.done` / `statusMap.done` |

- Landed on the base branch, or PR open in `pr` mode: transition to **In Review** and leave a
  ticket comment with the testing brief, so whoever verifies knows what to click. Write the
  comment in `reporting.language` and `reporting.commentStyle`.
- Pushed to a local branch only, in `push-to-main` mode: status stays In Progress; say that In
  Review comes when it lands on the base branch. Transition when the developer says it did.
- Risky change to app behaviour (data isolation, auth, migrations, a gateway): the critic in
  Step 5 is not optional. Pipeline change: no critic, but watch the first CI run after the push
  to the end.
- **Tell the project channel before a risky push.** If `slack.projectChannel` is set, offer —
  never auto-send — a one-paragraph update:

  ```
  ${CLAUDE_PLUGIN_ROOT}/skills/slack/scripts/post_message.py post \
    --channel <slack.projectChannel> --body-file <file> --workspace <slack.workspace>
  ```

  Write the paragraph, show it, and post only on an explicit yes. If no channel is configured,
  just remind the developer to tell the team. Nobody is waited for, unless the change breaks a
  contract an existing consumer relies on (removed or renamed API field, event field, column,
  CLI flag): then the area owner's ok comes first.
- **Done** only when the developer says the change is in production and was checked there. If
  they ask for Done before that, say which status matches where the code is and ask once; a
  repeated "Done" is their call.
- **Synthetic `LOCAL-` key or `tracker: "none"`:** commit and push work the same; no tracker
  calls at any point.
- If a matching transition does not exist, report the available transitions and ask which to
  use. Do not guess.

## Don'ts

- Don't commit or push without the developer's yes to the question in Step 7, and never with
  `git add -A`. No `stash`, `reset`, `rebase`, `merge`, `checkout` or force-push at all: when
  the tree or the remote is not what you expected, describe it and stop. The offer is yours,
  the decision is theirs.
- Don't move the ticket ahead of the code: In Review means it is on the shared branch, Done
  means checked in production. Never offer Done at the end of a local session, never transition
  silently.
- Don't create tickets in this skill. If the user wants one created before implementing, that
  is a separate, explicitly confirmed step.
- Don't fabricate browser-test results. If the browser tools are not loaded, drive what you can
  headlessly and mark browser-only scenarios as needing a fresh session.
- Don't skip verification for UI changes just because the code compiles. Compilation is not the
  feature working.
- Don't start editing with interview questions outstanding, and don't ask them as a list: one
  question per message.
- Don't build a rung nobody asked for: no schema, auth, config system or abstraction "for later".
- Don't call the task done without Step 3b (R2+) and Step 6 (R1+). Reading your diff is not
  reviewing it.
- Don't touch the CI queue: no cancelling, re-queuing or triggering builds. A build you did not
  expect belongs to someone else; say what you see and leave it.
- Don't auto-write documentation. Step 4 offers, the user decides.
- Don't restart, rebuild, migrate or nuke the local stack while another live session holds
  `stack-in-use`, and don't push from a checkout another session shares without saying whose
  commits ride along. The board says who and why.
