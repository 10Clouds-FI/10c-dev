---
name: jira
description: >-
  Read, manipulate and administer Jira Cloud tickets from a session. Search with JQL across every
  accessible project, get full issue detail with comments and available transitions, create,
  comment, transition, assign, browse boards (kanban and scrum auto-detected), list projects, and
  reach anything else through a raw REST escape hatch. Per-user API token stored outside the repo,
  with a first-run setup walkthrough. Use for "/jira", "find a jira ticket", "create a ticket for",
  "what's assigned to me in jira", "comment on ABC-123", "move ABC-123 to in progress", "assign
  ABC-123 to someone", "search jira for", "JQL", "board overview", or any reference to a Jira
  issue key or a *.atlassian.net link.
metadata:
  version: 1.0.0
  title_en: Jira
  summary_en: "Reads, changes and administers Jira Cloud tickets: JQL, comments, transitions, assignments, boards."
  category: [connectors]
---

# jira

A per-user Jira Cloud client: ten small Python scripts plus a raw REST escape hatch. Python 3
standard library only — nothing to `pip install`. Nothing about any particular company is baked
in; the site and the credential both come from configuration, and a fresh install has neither
until someone runs `setup.py`.

## First run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/setup.py"
```

It asks for the Jira site URL, the account's email, and an API token created at
<https://id.atlassian.com/manage-profile/security/api-tokens>; validates the pair against
`GET /rest/api/3/myself`; caches the resulting `accountId`; and writes the profile with mode 600.
The token is read with `getpass` and never printed back. Re-run it to rotate a token or to add a
second site.

**Never write the credentials file from the assistant.** Always invoke `setup.py`, so the token is
entered off-screen and validated before it is stored.

## Which site, which credential

Two independent questions, answered separately.

**Site**, first match wins:

1. `--site <url-or-host>` on any script (`https://acme.atlassian.net`, `acme.atlassian.net`, or the bare Cloud slug `acme`)
2. `JIRA_SITE` in the environment
3. `jira.site` in the consuming repo's `.claude/task-flow.json` (found by walking up from the working directory)
4. the site stored by `setup.py` (its `default` profile)
5. otherwise the scripts exit 2 with `JIRA_SITE_MISSING` and tell the user to run `setup.py`

**Credential**, first match wins:

1. `JIRA_EMAIL` + `JIRA_API_TOKEN` in the environment — both, or neither; half a pair is ignored rather than mixed with the file
2. `$JIRA_PLUGIN_DATA/jira/credentials.json` — the explicit override, for a caller that knows where this skill keeps its data
3. `$CLAUDE_PLUGIN_DATA/jira/credentials.json` — the host's persistent per-plugin directory, which is where it normally lives
4. `~/.claude/10c-dev/jira/credentials.json` — the fallback when neither variable is set

Whichever of those paths exists first is read; when none does, the first one is where `setup.py`
writes and the one the error message names.

The environment tier is what makes the skill work in a container with no home directory to write
to: inject the two variables and no setup run is needed.

## `.claude/task-flow.json`

Optional, lives in the repo being worked on, committed so the whole team shares it:

```json
{
  "jira": { "site": "https://acme.atlassian.net", "projectKey": "ABC" },
  "statusMap": {
    "todo": "To Do",
    "in_progress": "In Progress",
    "in_review": "In Review",
    "done": "Done"
  }
}
```

## The scripts

All take `--json` for machine-parseable output and `--site`; pagination is `--limit N` everywhere,
`--cursor TOKEN` for JQL search, `--start N` for the offset-paginated endpoints.

| Script | One line |
|---|---|
| `setup.py` | Interactive first run: site, email, API token; validates and stores them |
| `my_issues.py` | Issues assigned to the authenticated user (`--status`, `--project`, `--include-done`) |
| `jql_search.py` | `jql_search.py 'JQL' [--fields a,b] [--limit N] [--json]` — any JQL query |
| `get_issue.py` | `get_issue.py KEY` — one issue, plus `--with-comments` / `--with-transitions` |
| `create_issue.py` | `--project --type --summary [--description --assignee --labels --parent --priority]` |
| `comment.py` | `comment.py KEY "body text"` — body is a POSITIONAL argument, wrapped in ADF |
| `transition.py` | `transition.py KEY --to "Name"` (or `--id`, or `--list` to discover) |
| `assign.py` | `assign.py KEY <email>` — also `me`, a raw accountId, or `-1` to unassign |
| `list_projects.py` | Projects the user can see (`--query` filters server-side) |
| `board_overview.py` | `--board <id>` or `--project <KEY>`; kanban columns or scrum sprints, auto-detected |
| `jira_api.py` | Raw REST passthrough: `jira_api.py GET /rest/api/3/serverInfo [--body …] [--query k=v]` |
| `test_auth.py` | Offline tests for site resolution and the credential tiers (no network) |

Full call form from a session:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/<script>.py" [--site <url>] [args]
```

## Ticket-status convention

The `implement` skill drives a ticket through four states, and **the status follows the code**:

| State | When |
|---|---|
| To Do | picked up, nothing written yet |
| In Progress | work is happening locally |
| In Review | pushed — running somewhere other than the author's machine |
| Done | a human confirmed it in production |

No skill moves a ticket ahead of the code. The four names above are defaults; a team whose
workflow calls them something else (or whose Jira is localized) sets `statusMap` in
`.claude/task-flow.json` (full schema: `templates/task-flow.schema.md`) and the skills use those names instead. `transition.py KEY --list` is the
way to discover what a given workflow actually offers — transition ids are workflow-specific and
must never be hardcoded.

## Key API facts (so the assistant does not guess)

- **Auth** is HTTP Basic with the user's API token, handled in `_auth.py`. The token never reaches stdout.
- **JQL search uses `/rest/api/3/search/jql`** with `nextPageToken` pagination; the legacy `/search` endpoint returns 410 GONE on Jira Cloud. The response has `isLast` but **no `total`** — use `POST /rest/api/3/search/approximate-count` when a count is needed.
- **`jql_search.py` returns a DEFAULT field set that does not include `description`**, so a freshly created issue reads back from a search with an empty description and looks as though the create dropped it. Pass `--fields` for more, and **verify a create with `get_issue.py`, never with a JQL search**.
- **Descriptions and comment bodies must be ADF** (Atlassian Document Format). `create_issue.py` and `comment.py` wrap plain text automatically via `_adf.text_to_adf`; blank lines split paragraphs.
- **`comment.py` takes the body as a positional argument**, so a long body composed in a file goes in as `comment.py KEY "$(cat body.txt)"`. Command substitution protects backticks and Markdown; there is no `--body-file`.
- **Issue-type and transition names are per-site and may be localized.** `--type Task` returning HTTP 400 `Specify a valid issue type` means the site's names are not English, not that the script is broken. Discover with `jira_api.py GET '/rest/api/3/issue/createmeta/<PROJECT>/issuetypes'` and `transition.py KEY --list`.
- **Boards split kanban vs scrum** — `board_overview.py` auto-detects via `/board/{id}/configuration`. Asking a kanban board for `/sprint` returns HTTP 400 `The board does not support sprints`.
- **Two pagination regimes**: JQL search uses a `nextPageToken` cursor (`_paginate.cursor_paginate`); everything else uses `startAt`/`maxResults`/`values`/`isLast`/`total` (`_paginate.offset_paginate`).
- **User refs**: `me`, an email, or a raw accountId are interchangeable — `_auth.resolve_user()` handles all three.
- **Issue refs**: `ABC-123` or `https://acme.atlassian.net/browse/ABC-123` — `get_issue.normalize_key()` handles both.

## Error sentinels (one line on stderr)

| Sentinel | Meaning | What to do |
|---|---|---|
| `JIRA_SITE_MISSING` | No site from the flag, the env, task-flow.json or storage | Pass `--site`, or run `setup.py` |
| `JIRA_CREDS_MISSING` | No credentials file, or no profile for the resolved site | Run `setup.py`, or set `JIRA_EMAIL` + `JIRA_API_TOKEN` |
| `JIRA_AUTH_EXPIRED` | Token rejected (401) mid-session | Re-run `setup.py` |
| `JIRA_RATE_LIMITED` | 429 after one automatic retry | Wait and retry |
| `JIRA_NOT_FOUND` | 404 on an issue or board | Could be missing OR no permission — say so |
| `JIRA_BAD_REQUEST` | 400, with the Jira error body printed | Read the body and self-correct |

## Reference files

- `references/jql-cheatsheet.md` — JQL grammar, idioms, and the traps (`currentUser()`, date units, case-sensitive status names, pagination order)
- `references/rest-api-paths.md` — curated endpoint paths beyond the ergonomic scripts, for `jira_api.py`

## Conventions for the assistant

- **A ticket referenced by key or URL** → `get_issue.py KEY --with-transitions`, so the next action already has its options.
- **Before creating an issue**, confirm project, type and summary with the human. Do not guess the type name on a site you have not listed types for.
- **Before transitioning**, run `transition.py KEY --list` whenever the request is vague ("move it to done") and the workflow might have several Done-like states.
- **For admin work** — projects, permissions, sprints, attachments, worklogs, issue links — use `jira_api.py` with the right path and tell the user which endpoint you are hitting and why.
- `developer.atlassian.com` is heavy enough to defeat summarizing web fetches; `curl -sL` the page and extract what you need instead.
