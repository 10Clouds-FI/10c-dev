# `.claude/task-flow.json` — the per-repo config

Everything project-specific that this plugin needs lives in **one file in the consuming
repo**: `.claude/task-flow.json`. The plugin itself ships no project values. Copy
`templates/task-flow.json` into your repo, replace the placeholders, commit it.

The file is optional. Without it the skills fall back to: no tracker, base branch `main`,
`git.mode` `main`, and a validation gate guessed from `package.json` / `Makefile` /
CI config — and they say so out loud rather than pretending.

Unknown keys are ignored, so a repo may carry extra fields for its own tooling.

---

## Fields

### `tracker` — string, required in practice (default `"none"`)

`"jira"` or `"none"`. `"none"` means **every ticket step is skipped** — the same path a
synthetic `LOCAL-<date>-<time>` key takes. The work still gets the interview, the spec, the
tests, the verification and the review; it just never touches a tracker.

**A repo with `tracker: "none"` cannot meet the "every change that reaches `main` has a ticket"
rule.** `none` and `LOCAL-…` keys are for local, non-shipping work only (R0/R1, throwaway
spikes). Before a push to the base branch the workflow requires a real ticket key, and offers to
draft one.

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
| `projectChannel` | string | Channel id (`C…`) for the project's channel. When set, the `implement` skill **offers** a one-paragraph heads-up before a risky push and posts it as the developer only on an explicit yes. It never posts by itself, and the push waits until the heads-up is posted. |

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
| `baseBranch` | string | `main` | The shared branch. Code on it, once deployed to staging, counts as **In Review**. Also the merge-base for reviews, and the base the board hooks diff a push against. |
| `remote` | string | `origin` | Remote name; the board hooks use `<remote>/<baseBranch>` to work out which commits a push carries. |
| `mode` | `"main"` \| `"pr"` | `main` | The **default** answer to "push or PR?" at the commit offer, not a hard rule. `main`: commit and push straight to `baseBranch`. `pr`: work on a branch, push it, open a PR with `gh pr create` and the ticket key in the title. Either way the developer can pick the other for one change (a push to `main`, or a PR when a change needs a second pair of eyes). A ticket is In Review only once the code is on staging, not when the PR opens. `push-to-main` is accepted as an alias of `main`. |
| `branchPrefix` | string | `feature/` | Prefix for branch names in a PR: `<branchPrefix><KEY>-<slug>`. |
| `prodBranch` | string | — | Optional. The branch that represents production, if promotion is a merge rather than a deploy. **Done** still requires a human to confirm they checked it there. |

### `verify` — object, optional

The validation gate. Nothing here is inferred: the commands are run exactly as written, from
the repo root, in order.

| Key | Type | Meaning |
|---|---|---|
| `commands` | string[] | The default gate, run on every task. |
| `byArea` | object | Map of **path prefix → command list**. A task that touched a file under a prefix also runs that prefix's commands. A file may match several prefixes; run each matching set once. |
| `e2e` | string | The local end-to-end command (e.g. `npx playwright test`). Run at R2+ for every "done when" condition that describes a user flow. |

A failing gate command is a **blocker** finding in the review, whoever broke it.

### `risky` — array, optional

The areas where a mistake costs the most. A change that touches one is **risky**: the Critic is
mandatory (never skipped), and the push offer waits for the heads-up to the project channel.
Risk is classified right after the Spec.

Each entry is either a **label string** (the agent judges whether the change touches it) or an
object `{ "label": string, "paths": string[] }` (the globs make the match mechanical, and let a
hook check a push). Both forms may be mixed.

Default when the key is absent, the labels from the 10Clouds process: `tenant isolation`,
`authorization`, `migrations`, `pipelines`, `chat gateway`. Setting the key **replaces** the
defaults. A change near a core capability of the project model is treated as risky too.

### `owners` — object, optional

Map of **path prefix → person or handle** (`@api-team`, a name, an email). A contract break
(an API shape, a schema, a shared interface) needs the owner of the area's approval before the
push. The key `"*"` is the fallback; the value `"codeowners"` means "look the path up in
`CODEOWNERS`". When the key is absent, `CODEOWNERS` is used; when that has no match either, the
skill names the project model's owner or asks.

### `ci` — object, optional

How the workflow follows a push to staging and production. The plugin ships no CI templates; it
**checks that the repo has these gates and watches them**.

| Key | Type | Meaning |
|---|---|---|
| `unit` | object | The unit gate. `watch`: a command that prints the run for a commit (`{sha}` is substituted), for example a `gh run list --commit {sha} …`. `blocksDeploy` (bool): true when only a green run deploys. |
| `e2e` | object | The end-to-end gate (Playwright, full stack). `watch`: as above. `blocksProduction` (bool): true when production waits for a green run. |
| `staging` | object | `url`, and `deployed`: a command that signals the commit is live on staging. A ticket moves to **In Review** only after the unit gate is green and this signals. |
| `production` | object | `url` of the production app, used by the production check. |

All keys are optional. When a gate has no `watch`, the skill falls back to `gh run` and says so.
A red run keeps the ticket In Progress.

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

### `stackCommands` — string[], optional

Commands that mean "this restarts the shared local stack". Read by the session-board hooks:
running one while a neighbouring session holds `stack-in-use` asks first. Each entry is a regex
or a plain command prefix, matched at the start of a shell command (after `;`, `&&`, `|` or
`(`); an entry that is not a valid regex is matched literally. Setting a non-empty list
**replaces** the defaults: `make (start|stop|restart|recreate|down|nuke)` and
`docker compose (up|down|restart)`. Example: `["make start", "docker compose down", "tilt (up|down)"]`.

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

A repo with no tracker and one lint command (local work only, it cannot ship to `main` without a real ticket):

```json
{
  "tracker": "none",
  "git": { "baseBranch": "main", "mode": "main" },
  "verify": { "commands": ["make lint", "make test"] }
}
```
