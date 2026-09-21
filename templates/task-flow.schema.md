# `.claude/task-flow.json` — the per-repo config

Everything project-specific that this plugin needs lives in **one file in the consuming
repo**: `.claude/task-flow.json`. The plugin itself ships no project values. Copy
`templates/task-flow.json` into your repo, replace the placeholders, commit it.

The file is optional. Without it the skills fall back to: no tracker, base branch `main`,
`git.mode` `push-to-main`, and a validation gate guessed from `package.json` / `Makefile` /
CI config — and they say so out loud rather than pretending.

Unknown keys are ignored, so a repo may carry extra fields for its own tooling.

---

## Fields

### `tracker` — string, required in practice (default `"none"`)

`"jira"` or `"none"`. `"none"` means **every ticket step is skipped** — the same path a
synthetic `LOCAL-<date>-<time>` key takes. The work still gets the interview, the spec, the
tests, the verification and the review; it just never touches a tracker.

### `jira` — object, required when `tracker: "jira"`

| Key | Type | Required | Meaning |
|---|---|---|---|
| `site` | string | yes | Atlassian site URL, e.g. `https://your-org.atlassian.net`. Also readable from the `JIRA_SITE` env var. |
| `projectKey` | string | yes | Default project key, e.g. `ABC`. The **ticket key prefix always wins** over this: `PROJ-9` is handled as project `PROJ` even in an `ABC` repo. |
| `board` | number | no | Board id, for sprint lookups and board views. |
| `cloudId` | string | no | Atlassian cloud id, used by the `atlassian` MCP server. When absent it is fetched once per session from `getAccessibleAtlassianResources`. |

Credentials are never stored here. The `jira` skill's scripts read `JIRA_EMAIL` /
`JIRA_API_TOKEN` from the environment or `$CLAUDE_PLUGIN_DATA/jira/credentials.json`.

### `slack` — object, optional

| Key | Type | Meaning |
|---|---|---|
| `workspace` | string | Workspace domain, e.g. `your-org.slack.com`. |
| `projectChannel` | string | Channel id (`C…`) for the project's channel. When set, the `implement` skill **offers** a one-paragraph heads-up before a risky push and posts it only on an explicit yes. It never posts by itself. |

### `statusMap` — object, optional

Maps the four canonical phases to the status names this board actually uses. Keys:
`todo`, `in_progress`, `in_review`, `done`, plus an optional `blocked`. Values are the exact
status names on the board, in whatever language the board uses. Used to resolve a transition
by name when `transitionIds` has no entry for the phase.

Defaults: `To Do`, `In Progress`, `In Review`, `Done`.

### `transitionIds` — object, optional

Workflow transition ids per phase (`todo`, `in_progress`, `in_review`, `done`), as strings.
When a phase has an id here, it is used directly — faster and immune to renamed statuses.
When it is absent, the transition is resolved by the `statusMap` name, case-insensitively.
If neither resolves, the skill reports the available transitions and asks; it never guesses.

### `git` — object, optional

| Key | Type | Default | Meaning |
|---|---|---|---|
| `baseBranch` | string | `main` | The shared branch. Code on it counts as **In Review**. Also the merge-base for reviews. |
| `remote` | string | `origin` | Remote name. |
| `mode` | `"push-to-main"` \| `"pr"` | `push-to-main` | `push-to-main`: commit and push straight to `baseBranch`; the team does not open pull requests and the skill never proposes one. `pr`: work on a branch, push it, open a PR with `gh pr create` and the ticket key in the title; an open PR counts as In Review. |
| `branchPrefix` | string | `feature/` | Prefix for branch names in `pr` mode: `<branchPrefix><KEY>-<slug>`. |
| `prodBranch` | string | — | Optional. The branch that represents production, if promotion is a merge rather than a deploy. **Done** still requires a human to confirm they checked it there. |

### `verify` — object, optional

The validation gate. Nothing here is inferred: the commands are run exactly as written, from
the repo root, in order.

| Key | Type | Meaning |
|---|---|---|
| `commands` | string[] | The default gate, run on every task. |
| `byArea` | object | Map of **path prefix → command list**. A task that touched a file under a prefix also runs that prefix's commands. A file may match several prefixes; run each matching set once. |

A failing gate command is a **blocker** finding in the review, whoever broke it.

### `app` — object, optional

How to see the thing working — this is what "prove it on the artifact a human uses" needs.

| Key | Type | Meaning |
|---|---|---|
| `start` | string | Command that brings the local stack up, e.g. `make start`. |
| `urls` | object | Map of **label → URL**. Free-form labels (`app`, `admin`, `api-docs`, …). The skill picks the one that matches the change and drives it in the browser. |

### `rules` — object, optional

Map of **path prefix → list of rule files** (repo-relative). Before editing a file under a
prefix, the matching rule files are read and treated as mandatory.

When this key is absent, the skills fall back to reading every `.claude/rules/*.md` whose name
matches the area being touched, plus the repo's `CLAUDE.md` (and `CONTRIBUTING.md` /
`docs/gotchas.md` when present).

### `hotspots` — string[], optional

Paths and globs where parallel sessions collide — a router table, a root component, a
migrations directory. Read by the session-board hooks: an edit to a hotspot that a neighbouring
session is also holding raises a blocker before the edit, not after the conflict.

### `reporting` — object, optional

| Key | Type | Default | Meaning |
|---|---|---|---|
| `language` | string | `en` | Language for ticket comments and status updates. Chat follows the human's language; **durable artifacts — commits, code, docs, the project model — are always English regardless of this setting.** |
| `commentStyle` | string | `technical` | Register for ticket comments, e.g. `technical`, `plain`. |

### `notes` — string[], optional

Free-text quirks of this board or repo that a session should know before it starts: a missing
status, a transition whose name does not match the status it leads to, a query that returns
too much. Read as context, never as instructions.

---

## Minimal file

A repo with no tracker and one lint command:

```json
{
  "tracker": "none",
  "git": { "baseBranch": "main", "mode": "pr", "branchPrefix": "feature/" },
  "verify": { "commands": ["make lint", "make test"] }
}
```
