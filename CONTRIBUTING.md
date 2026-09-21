# Contributing

## Before you open a PR

```bash
# tests
python3 -m pytest hooks/tests skills/jira/scripts -q

# the manifests load
claude plugin validate .

# no company-internal identifiers leaked in — this must print nothing
# (it excludes itself, since the pattern below would otherwise match this line)
grep -rniE '10cloudsfi|aiconsole|\baic\b' . --exclude-dir=.git --exclude=CONTRIBUTING.md
```

The last one is not a formality. This repository is public and generic by design: no internal
hostnames, cloud ids, channel ids, project keys, people's names or email addresses. Examples
use `ABC-123`, `your-org.atlassian.net`, `C0123456789`. English only.

## Trying a change

```bash
claude --plugin-dir .
```

loads the working copy for that session, ahead of any installed copy. `/reload-plugins` picks
up edits to `hooks/`, `.mcp.json` and `agents/` without a restart; a `SKILL.md` takes effect
immediately.

## Layout

- One skill per directory: `skills/<name>/SKILL.md`, with anything long split into
  `references/` and anything executable into `scripts/`. The directory name is the invocation
  name (`/10c-dev:<name>`).
- Agents in `agents/`, one Markdown file each.
- Hooks in `hooks/hooks.json`. Scripts referenced from it use `${CLAUDE_PLUGIN_ROOT}`.
- MCP servers in `.mcp.json` at the plugin root. **No secrets, ever** — anything key-based is
  added by the user at local scope.
- `commands/`, `agents/`, `skills/` and `hooks/` live at the repo root, never inside
  `.claude-plugin/`. Only `plugin.json` and `marketplace.json` go in there.
- Project-specific values belong in the consuming repo's `.claude/task-flow.json`, never
  hardcoded in a skill. If a skill needs a new value, add it to `templates/task-flow.json` and
  document it in `templates/task-flow.schema.md` in the same PR.
- Python scripts are standard-library only and target 3.10+, so a user needs no install step.

## Versioning

`version` in `.claude-plugin/plugin.json` is semver, and it is what tells an installed copy
that an update exists — bump it in the PR that changes behaviour. Patch for a fix, minor for a
new skill or a new config field, major for a change that breaks an existing
`.claude/task-flow.json`.

## Style

- English, no emoji in skill bodies or commit messages.
- Commit format: `<type>(<scope>): <subject>`, imperative.
- A skill's `description` frontmatter is what decides whether Claude reaches for it — write it
  as trigger phrases a user would actually say, not as a summary.
