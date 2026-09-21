# JQL cheat sheet

For composing arguments to `jql_search.py` and the JQL field on `jira_api.py POST /rest/api/3/search/jql`. JQL is Jira Query Language — a SQL-ish filter language. Keywords and operators are NOT case-sensitive; values are.

## Core syntax

```
field operator value [AND|OR field operator value ...] [ORDER BY field ASC|DESC]
```

## Most useful fields

| Field | Examples |
|---|---|
| `assignee` | `assignee = currentUser()`, `assignee = "dev@example.com"`, `assignee was currentUser()`, `assignee is EMPTY` |
| `reporter` | same shape as assignee |
| `project` | `project = ABC`, `project in (ABC, DEF)` |
| `status` | `status = "In Progress"`, `status != Done`, `status in ("To Do", "In Progress")` |
| `statusCategory` | `statusCategory = "In Progress"` (categories: `new`, `indeterminate`, `done`) — broader than status |
| `issuetype` | `issuetype = Task`, `type in (Task, Story, Bug)` |
| `priority` | `priority = High`, `priority >= Medium` |
| `labels` | `labels = backend`, `labels in (backend, "tech-debt")` |
| `created` / `updated` / `resolved` / `due` | `updated >= -7d`, `created >= "2026-05-01"`, `due < endOfWeek()` |
| `sprint` | `sprint in openSprints()`, `sprint in closedSprints()`, `sprint = "Sprint 12"` |
| `text` | `text ~ "checkout bug"` (matches summary + description + comments) |
| `summary` | `summary ~ "migration"` (text-match; supports `~`) |

## Functions (case-insensitive)

- `currentUser()` — the authenticated user
- `now()`, `startOfDay()`, `endOfDay()`, `startOfWeek()`, `endOfWeek()`, `startOfMonth()`, `endOfMonth()`
- `openSprints()`, `closedSprints()`, `futureSprints()`
- `unreleasedVersions()`, `releasedVersions()`
- `membersOf("group-name")`

## Date math

```
updated >= -7d           # last 7 days
created >= -1w           # last week
due <= endOfWeek()       # due this week
resolved >= "2026-01-01" # absolute date
```

Units: `d` (days), `w` (weeks), `m` (minutes — NOT months), `h` (hours), `M` (months). The lowercase-m-means-minutes gotcha bites people regularly.

## Operators

- `=`, `!=`, `<`, `<=`, `>`, `>=`, `IN`, `NOT IN`
- `~` (contains substring — text search), `!~`
- `IS EMPTY`, `IS NOT EMPTY`, `WAS`, `WAS IN`, `CHANGED`

## Common idioms

```
# My open work, most recently touched first
assignee = currentUser() AND statusCategory != Done ORDER BY updated DESC

# Everything created in one project this week
project = ABC AND created >= startOfWeek()

# Tickets where I'm mentioned in a comment
text ~ "currentUser()"   # WRONG — currentUser() does not work inside text ~
comment ~ "<my-name-substring>"   # do this instead

# Stale unassigned tickets
project = ABC AND assignee IS EMPTY AND updated <= -14d

# Cross-project search for a term
text ~ "payment gateway" ORDER BY updated DESC

# Anything urgent still open
priority = Highest AND statusCategory != Done

# Work that has not moved in a week
assignee = "dev@example.com" AND statusCategory = "In Progress" AND updated <= -7d

# Recently resolved, for a review meeting
project = ABC AND resolved >= -14d ORDER BY resolved DESC
```

## Gotchas

- **No `total` in `/search/jql` responses** — use `POST /rest/api/3/search/approximate-count` if a count matters.
- **The `sprint` field only works on scrum boards.** On a kanban board (`type: "simple"`) `sprint in openSprints()` returns empty rather than erroring.
- **Status names are case-sensitive and workflow-specific**: `status = "in progress"` ≠ `status = "In Progress"`, and a team may have several Done-like states with custom names. Discover with `transition.py <KEY> --list` or `GET /rest/api/3/project/{key}/statuses` rather than guessing.
- **Order matters in pagination**: always add `ORDER BY updated DESC` (or another stable field) when paginating with `nextPageToken`, otherwise pages drift.
- **Quoting**: status names with spaces need double quotes; project keys must NOT be quoted.
- **Localized Jira sites rename issue types and transitions.** If `--type Task` is rejected with `Specify a valid issue type`, the site's names are not English — list them with `jira_api.py GET '/rest/api/3/issue/createmeta/<PROJECT>/issuetypes'`.
