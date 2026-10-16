---
name: implement
description: "Drives the full build cycle for a task. Drafts a ticket when work starts from a Slack thread or a message, moves the ticket to In Progress, runs the `coding` skill (rung, interview, spec, tests first by the test-design agent, code), verifies on the running app, has the code-review agent review the diff, closes with `cleanup` and a project-model update, runs the critic (mandatory on risky or core changes), then offers to commit and push to `main` or open a PR. The ticket follows the code: In Progress locally, In Review once on staging after green CI, Done once a human checked production (see `release-check`). Accepts a real ticket key, a synthetic local key for work that never ships, or no key at all."
metadata:
  version: 1.0.0
  title_en: Implement a task end to end
  summary_en: The build cycle — ticket, rung, interview, spec, minimal build, verification, code review, critic, cleanup, commit.
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
| `tracker` | `"jira"` → do the ticket steps; `"none"` → no tracker: local work only, it cannot go to `main` (see Key types) |
| `jira.site`, `jira.projectKey`, `jira.board`, `jira.cloudId` | tracker access |
| `statusMap`, `transitionIds` | the names/ids this board uses for To Do / In Progress / In Review / Done |
| `git.baseBranch`, `git.remote`, `git.mode`, `git.branchPrefix` | where the code goes; `mode` (`main` or `pr`, default `main`; `push-to-main` is an alias) is only the default answer to the commit question (Step 7) |
| `risky` | array of labels or `{label, paths[]}`; default labels: tenant isolation, authorization, migrations, pipelines, chat gateway (Step 2) |
| `owners` | path prefix → handle; `"*"` is the fallback; the value `"codeowners"` or a missing key means look it up in `CODEOWNERS` (Step 7) |
| `ci` | `unit {watch, blocksDeploy}`, `e2e {watch, blocksProduction}`, `staging {url, deployed}`, `production {url}`; `watch` takes `{sha}` (Step 8) |
| `verify.e2e` | the local end-to-end command, run in Step 3 |
| `verify.commands`, `verify.byArea` | the validation gate, and the extra commands for a touched area |
| `app.start`, `app.urls` | how to bring the app up and where to look at it (Step 3) |
| `rules` | which rule files to read before touching which paths (Step 2) |
| `slack.projectChannel`, `slack.workspace` | the optional heads-up in Step 7 |
| `reporting.language`, `reporting.commentStyle` | how ticket comments are written |
| `notes` | board quirks the team already learned |

If the file does not exist, treat it as `tracker: "none"` (local work only), `git.baseBranch: "main"`,
`git.mode: "main"`, no verify commands, and say in one line that the repo has no
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
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/comment.py KEY "..."
   ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/jql_search.py 'project = ABC AND status = "In Progress"'
   ```

   They read the site from `.claude/task-flow.json` (`jira.site`) or the `JIRA_SITE` env var,
   and credentials from `JIRA_EMAIL` / `JIRA_API_TOKEN` or
   `$CLAUDE_PLUGIN_DATA/jira/credentials.json`. First run:
   `${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/setup.py`.

**Never stop because the MCP server is not authenticated** — fall through to the scripts. Only
if both paths fail do you say so and offer to keep the work local (`LOCAL-` key) rather than guessing ticket state.

**The project is whatever the ticket key prefix says.** Derive it from the key, never hardcode
a project. If the user names a different project than the key implies, follow the user.

## Preconditions

- A task is identified: a real tracker key, a synthetic `LOCAL-` key, or a source to draft a
  ticket from (Step 0).
- The developer has explicitly confirmed proceeding.

There are no execution modes. The rung (Step 2) decides how much ceremony the work gets, and
the developer agrees the plan once; after that Claude Code's own edit prompts cover each step.

### Key types

- **Real ticket key** (matches `^[A-Z]+-\d+$`, e.g. `ABC-123`): do all tracker transitions
  against the key's own project.
- **Synthetic local key** (starts with `LOCAL-`), or `tracker: "none"`: no tracker calls. Allowed
  only for work that stays local: R0 probes and R1 proofs of concept. **Every change that reaches
  the base branch has a real ticket, a documentation fix included.** Before any push to
  `main`, a `LOCAL-` task needs a real key: offer Step 0 to draft one, then continue with it.
  A repo with `tracker: "none"` cannot ship through this skill; say so and keep the work local.

When a step says "transition the ticket", read it as a no-op for local keys.

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

Other Claude Code sessions may be working in this repo on this machine right now. This is the
Shared board: its digest arrives in your context automatically from the plugin's hooks, but
before the ticket is opened look deliberately:

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

## Steps

### 0. No ticket yet: draft one

Applies when the work starts from a Slack thread, a client message, or a freeform request with
no key. Skip when the developer gave a real key. Nothing is coded before the ticket exists.

1. Read the source. A Slack link or thread: use the `slack` skill. A pasted message: use it as is.
2. Draft, in `reporting.language`: a one-line summary, a description (what is wanted, why, who
   asked, a link to the source) and 2 to 4 candidate "done when" conditions, each written as
   something a user can observe.
3. Show the draft to the developer. Edit until they agree.
4. On a yes, create the ticket: `mcp__atlassian__createJiraIssue`, or
   `${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/create_issue.py --project <KEY> --summary "..." --description "..."`.
   Never create it unasked.
5. Continue with the new key. The agreed conditions go into the spec in Step 2.

If the developer wants to stay local (R0 or R1 work), a `LOCAL-<date>-<time>` key is fine; see
Key types for what that rules out.

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

Then read the project model: if `docs/PROJECT_MODEL.md` exists, read it now. Use it to weigh the
task: a change near a `core` capability gets the interview, tests and the critic; a change to
something marked `legacy-keep` or `dead` gets the question "should this exist at all" before
any code. If the file does not exist, say so in one line and continue.

### 2. Build: rung, interview, spec, tests first, code

**The `coding` skill runs inside this step and is not optional.** Load it before the first
edit and follow its phases in order; this skill only says where they sit in the cycle:

| Phase | `coding` | Where in this skill |
|---|---|---|
| 1 | Say the rung out loud (R0 probe / R1 PoC / R2 MVP / R3 hardened) | here, before any edit; the developer can override it, stepping up needs their OK |
| 2 | Interview, one question per message | here, before designing; the ticket is input to the interview, not a substitute for it |
| 3 | Spec in chat: goal, out of scope, a plan with a check per step, 2 to 4 "done when" conditions from the user's side | here, in the conversation, never as a file in the repo |
| 4 | **Tests first**: the test-design agent derives unit and e2e tests from "done when", before any code | here, at R2 and R3 (optional at R1) |
| 5 | Write the code, step by step, area rules loaded | here |
| 6 | Prove it on the running app, then walk each "done when" | Step 3 below |
| 7 | Code review of the diff by an independent agent (R2+) | Step 3b below |
| 8 | Closing reflection with `cleanup` | Step 5 below |
| 9 | Project model | read in Step 1; update in Step 5 |

The rung is a one-way ratchet: step up only after saying so and getting agreement, never
quietly down. **Only R2 and R3 go to `main`.** R0 and R1 stay local or throwaway; shipping
them means stepping up to R2 with the developer's agreement. A one-line fix that ships is R2
with a small ceremony, not R0.

**Classify risk right after the spec and say it out loud.** The change is **risky** when it
touches one of the configured `risky` areas (default labels: tenant isolation, authorization,
migrations, pipelines, chat gateway; a `paths` list, if the config gives one, decides by path). It is
**core** when the project model marks the touched capability `core`. The critic is mandatory
for both (Step 6).

**Tests first.** At R2 and R3, spawn the `test-design-agent` before writing any code. Pass it
the ticket key, the rung, the repo path, the spec's "done when" conditions and the out-of-scope
list, never the plan or this conversation. It writes failing unit and e2e tests (a bug gets a reproducing test) and
returns the cases and the files. You may not weaken, delete or edit those tests without telling
the developer why. Every "done when" condition that is a user flow gets an e2e test. At R1 the
agent is optional.

**Write the code** one plan step at a time, each with its check. The developer agrees the plan
once; Claude Code's edit-permission prompts are the per-step acceptance. After each step, show
what changed and the check result, and surface changes incrementally. Do not batch ten files
of edits before the first check-in. Run `verify.commands` plus the `verify.byArea` set for the
touched area, and the tests from the test-design agent.

**Load the rules for what you are touching before the first edit.** They are mandatory, not
advisory:

- Read the `rules` map in `.claude/task-flow.json`: every entry whose path prefix matches a
  file you are about to touch names the rule files to read first.
- If the repo has no `rules` map, read every `.claude/rules/*.md` whose name matches the area
  you are in, plus the repo's `CLAUDE.md` (and `CONTRIBUTING.md` / `docs/gotchas.md` if
  present).
- A rule that seems wrong is surfaced to the developer before you deviate, never silently
  ignored.

### 3. Verify on the running app

Every change is verified on the running app, UI or not.

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
- Run `verify.e2e` if the config has it.
- If the change affected the UI, exercise it at the relevant address from `app.urls` and run a
  short self-correction loop on failures.
- If the change is purely backend or non-UI (a migration, an endpoint, a background job),
  exercise it directly (tests, an API call, worker logs) and say so explicitly in the brief.
- **If the config lists area-specific verification** (`verify.byArea`) for a path you touched,
  run it — a command that CI skips is exactly the one that bites after the push.
- Finish with the per-condition table from `coding` §6: each "done when" condition, how it was
  observed, and ✓, ✗ or "unverified (why)". A ✗ goes back to "write the code" (Step 2).

### 3b. Code review by an independent agent (R2 and above)

Spawn `code-review-agent` in a fresh context. Pass it the diff range (the current branch
against the base branch, uncommitted changes included), the ticket key and the spec, never this
conversation. It runs the `code-review` skill and returns findings ranked blocker, major,
minor, nit, plus the lint, type, test and breaking-change checks.

- **Blockers and majors:** you fix them yourself, then show the developer the report and what
  you fixed. If they want to read the report first or take the findings themselves, they can
  say so; fixing waits for them then. Re-run the checks after the fixes. All blockers and
  majors are fixed before commit.
- **Minors and nits:** a finding in a file the diff already touches is fixed now. Every other
  one is recorded for later as a comment on the ticket (a real key), or listed in the final
  summary for a `LOCAL-` task. Do not widen the scope to fix files the change does not touch.
- A finding about pre-existing code goes into Step 5's cleanup list, not into a drive-by fix.
- Skip at R0 and R1 unless the developer asks.

### 4. Prepare a testing brief

The ticket already records *what* was done. Prepare a brief in the conversation. It is for the
developer, the ticket comment and the human who checks production. **The critic does not get
it**: it knows how the work was done, which the critic must never see.

- **Ticket or topic:** `<KEY>: <summary>`
- **Scenario:** ordered steps to verify the work, including the exact inputs and prompts that
  worked in Step 3
- **Expected outcomes:** per step, what the UI, API or worker should do
- **Regression watch-list:** areas this change could plausibly break

Keep the brief in the conversation. It does not need to be written to disk unless the user asks.

**Optional: capture learning.** If the session produced a non-obvious gotcha, offer to add it
to the repo's gotchas doc so the next developer does not rediscover it. Offer, never auto-write.

### 5. Close: cleanup and the project model

Runs after Step 4, at R1 and above, **before the critic on every change**, so the critic's PASS covers the final diff. Runs before anything is committed.

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

### 6. Critic

The critic is **mandatory** for a risky or core change (classified in Step 2) and does not
get asked about. For any other change, ask once: "Run the critic now, or go straight to
commit?" Skipping is allowed there, never on a risky change.

Cleanup (Step 5) has already run, so the PASS covers the final diff. The board treats any edit
after a PASS as unverified and asks before the push.

- Invoke the `critique-agent` with three inputs and nothing else: the ticket key, the
  "done when" conditions from the spec, and the URL where the app is running; on a re-run, also
  the list of scenarios the previous FAIL reported as failed. Not the code, not the diff, not
  the brief, not what worked in Step 3. For a `LOCAL-` key the conditions stand in for the
  ticket.
- Do not edit code or restart containers while it runs; its result is about the stack as it
  was when it started.
- It runs in an isolated context, builds its own attack plan (at least five scenarios, each
  "done when" condition among them) and returns PASS or FAIL.
- **Verdict:** record it for the board: `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py set --critic PASS` (or `FAIL`). A push of a risky change without a PASS after the last edit gets asked about.
- **PASS:** go to Step 7.
- **FAIL:** surface the report and go back to "write the code" in Step 2, then verify, review,
  cleanup and critic again. There is no "continue as is". The re-run covers the failed scenarios only.
  After 2 FAIL rounds stop and hand the report to the developer to decide.

The critic is not looped for nitpicks: a PASS ends it, and a re-run exists only to confirm a
fix to a FAIL.

### 7. Offer to commit and push; the ticket status follows the code

When the code works locally, the diff is reviewed and cleanup is done, **offer to commit and
push.** Do not wait to be asked, and do not do it unasked.

**Gates before the offer:**

- **Rung.** At R0 or R1, do not offer a push to `main`. Offer stepping up to R2 (with the
  tests, review and critic that implies), or keep the work local.
- **Ticket.** A `LOCAL-` key or `tracker: "none"` cannot go to `main`: offer Step 0 first to get
  a real key.
- **Risky change.** The push offer waits until the heads-up is posted (below). A contract break
  also waits for the area owner (below).
- **Identity.** Before the first commit, compare `git config user.name` and `user.email` with
  the developer and confirm once. Commits go under the developer's own name, never another
  identity or a bot. Mismatch: stop and ask.

**One question, two answers:** "Push to `<baseBranch>`, or open a pull request for a second
review?" with the proposed commit message in it. `git.mode` is only the default: `main`
makes the push the first answer, `pr` makes the PR the first. The developer picks per change.

- Before the push, `python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py check-push`: a non-zero exit
  names a neighbour that is pushing right now or shares this checkout, and lists the local
  commits your push would carry. Stop and show that to the developer; push only on their word.
  The `PreToolUse` hook asks the same question mechanically, so do not route around it.
- On yes: `git add` the files of this task only (never `-A`), commit in the repo's format
  (`<type>(<scope>): <subject>` unless the repo says otherwise), English, imperative, no emoji,
  one coherent change per commit (cleanup separately, see Step 5). The ticket key goes in the
  commit body, along with the Step 3b summary: verdict, counts per severity, one line per
  blocker/major and what was done about it.
- **Push to `main`:** commit on `git.baseBranch` and `git push`.
- **Pull request:** work on a branch named `<git.branchPrefix><KEY>-<slug>`, push it, then open
  a pull request with `gh pr create`, the ticket key in the title, and the testing brief in
  the body.
- Read the push result: a rejected push means someone else pushed first; fetch and tell the
  developer, do not force anything.
- On no: finish with a one-line summary and the testing brief from Step 4. Nothing else.

**Risky heads-up.** Before the push of a risky change, draft a one-paragraph update for
`slack.projectChannel`, show it, and post it as the developer only on an explicit yes:

```
${CLAUDE_PLUGIN_ROOT}/skills/slack/scripts/post_message.py post \
  --channel <slack.projectChannel> --body-file <file> --workspace <slack.workspace>
```

No channel configured: ask the developer to tell the team and confirm it is done. The push
waits until the heads-up is posted or confirmed.

**Contract break.** A removed or renamed API field, event field, column or CLI flag that an
existing consumer relies on needs the area owner's OK before the push. Name the owner from the
`owners` map in the config, `"*"` is the fallback; `"codeowners"` or no entry means `CODEOWNERS`, then the project model. Ask the developer to get
the OK, and wait for it.

### 8. After the push: CI, staging, In Review

The ticket's status says where the code IS, never how the conversation went. This skill never
moves a ticket ahead of it:

| Where the code is | Status | Transition |
|---|---|---|
| on a branch, in a worktree, uncommitted, or pushed but not yet deployed | In Progress | set in Step 1 |
| on staging, after a green CI | In Review | `transitionIds.in_review` / `statusMap.in_review` |
| promoted to production and checked there by a human | Done | `transitionIds.done` / `statusMap.done`, via `release-check` |

- **Follow the CI run** for the pushed SHA with `ci.unit.watch` (`{sha}` filled in, or
  `gh run watch`). A green unit gate plus `ci.staging.deployed` mean the code is on staging.
  Never cancel, re-queue or trigger a build.
- **Green and deployed:** transition to **In Review** and comment the testing brief, so whoever
  verifies knows what to click. Write it in `reporting.language` and `reporting.commentStyle`.
  Mention the e2e gate (`ci.e2e`) that must pass before production.
- **Red:** say so with the failing job, and keep the ticket In Progress. Fixing it is a new
  loop through Step 2.
- **Pull request:** the ticket stays In Progress while the PR is open. It becomes In Review
  only when the merged code is on staging.
- **No `ci` config:** say so, ask the developer to tell you when it is on staging, and
  transition then.
- **Done** is `release-check`'s job: invoke it with the key after a release, so a human checks
  production. Never offer Done at the end of a local session. If the developer asks for Done
  before that, say which status matches where the code is and point them to `release-check`.
- If a matching transition does not exist, report the available transitions and ask which to
  use. Do not guess.

## Don'ts

- Don't commit or push without the developer's yes to the question in Step 7, and never with
  `git add -A`. No `stash`, `reset`, `rebase`, `merge`, `checkout` or force-push at all: when
  the tree or the remote is not what you expected, describe it and stop. The offer is yours,
  the decision is theirs.
- Don't push R0/R1 work or a `LOCAL-` task to `main`.
- Don't move the ticket ahead of the code: In Review means it is on staging, Done means
  checked in production. Never transition silently.
- Don't create a ticket the developer has not agreed to. Step 0 drafts, shows and creates only
  on a yes.
- Don't write code before the tests exist (R2+), and don't weaken those tests quietly.
- Don't waive a critic FAIL, and don't skip the critic on a risky or core change.
- Don't give the critic or the review agent the code, the build conversation or the testing
  brief: the diff goes to the review agent, the ticket and conditions to the critic.
- Don't fabricate browser-test results. If the browser tools are not loaded, drive what you can
  headlessly and mark browser-only scenarios as needing a fresh session.
- Don't skip verification just because the code compiles. Compilation is not the feature
  working.
- Don't start editing with interview questions outstanding, and don't ask them as a list: one
  question per message.
- Don't build a rung nobody asked for: no schema, auth, config system or abstraction "for later".
- Don't call the task done without Step 3b (R2+) and Step 5 (R1+). Reading your diff is not
  reviewing it.
- Don't touch the CI queue: no cancelling, re-queuing or triggering builds. A build you did not
  expect belongs to someone else; say what you see and leave it.
- Don't auto-write documentation. Step 4 offers, the user decides.
- Don't restart, rebuild, migrate or nuke the local stack while another live session holds
  `stack-in-use`, and don't push from a checkout another session shares without saying whose
  commits ride along. The board says who and why.
