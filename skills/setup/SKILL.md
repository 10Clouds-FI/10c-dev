---
name: setup
description: One-time setup for the 10c-dev workflow — checks runtimes, connects and authenticates the ticket tracker and Slack, installs the browser automation, then interviews you to write this repo's .claude/task-flow.json and verifies every piece works.
metadata:
  version: 1.0.0
  title_en: 10c-dev setup
  summary_en: Onboards a machine and a repository onto the 10c-dev delivery workflow, one verified step at a time.
  category: [development]
---

You are onboarding a developer onto the `10c-dev` workflow, in this repository, on this
machine. Walk them through every prerequisite **one step at a time**, wait for confirmation,
then move on. Never batch several steps into one message: people get lost.

This skill sets up the **tooling**. It does not start the product's stack.

# Ground rules

- Go **one step at a time**. After each step ask "Done? Ready for the next?" and wait.
- Do not skip a step because it looks done. Verify with a concrete check: a command output, a
  file that exists, a tool call that returns real data.
- **Never read, print, echo or log a secret value.** Check existence only (`test -f <path>`,
  `[ -n "$VAR" ]`). If a script would print a token, don't run it that way.
- Run the verification commands yourself with Bash rather than asking the user to run them, and
  say what you are checking.
- If a check fails, stop and help fix it before continuing.
- `${CLAUDE_PLUGIN_ROOT}` is this plugin's directory; use it for every bundled script path.

# The steps (in order)

Open with a short hello, list the six steps so the user knows what is coming, then begin
**Step 1**.

## Step 1: runtimes

Check with Bash:

- `python3 --version` — **3.10 or newer** (the bundled Jira and board scripts are stdlib-only,
  but they use modern typing syntax)
- `node --version` — **20 or newer** (the Playwright MCP server runs through `npx`)
- `gh --version` — the GitHub CLI, used for PR-mode git flows and for reading CI
- `git --version`

For anything missing, give the exact install command for their OS (`brew install`, `apt`,
`winget`, or the vendor installer) and wait. `gh` is optional if the repo pushes straight to its
base branch and CI is not on GitHub — say so rather than blocking on it.

## Step 2: the ticket tracker

Ask first: **does this team track work in Jira, or not?** ("none" is a valid answer — the
workflow then runs entirely on synthetic `LOCAL-<date>-<time>` keys and skips every tracker
call. If they say none, skip to Step 3.)

For Jira, try the MCP server first, then fall back to the bundled scripts.

**2a — the `atlassian` MCP server.** This plugin declares it in `.mcp.json`
(`https://mcp.atlassian.com/v1/mcp`, OAuth per user).

1. `claude mcp list` — confirm `atlassian` appears. If it does not, the plugin's MCP servers
   were not trusted at install; `/mcp` reopens the prompt, or restart the session.
2. Trigger OAuth by making a real call — `mcp__atlassian__getVisibleJiraProjects`. A browser tab
   opens; the user signs in with their work account and approves.
3. Verify with **real data**: the returned project list must contain the project key this team
   actually uses. Do not move on until you see it.
4. Record the `cloudId` from `mcp__atlassian__getAccessibleAtlassianResources` — every
   `mcp__atlassian__*` call needs it, and it goes into `jira.cloudId` in Step 5.

**2b — the bundled scripts** (use these if the MCP server is unavailable, blocked by the
org, or the user prefers a token):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/setup.py
```

It asks for the site, the account email and an API token
(<https://id.atlassian.com/manage-profile/security/api-tokens>) and stores them outside the
repo, under `$CLAUDE_PLUGIN_DATA/jira/credentials.json`. `JIRA_EMAIL` / `JIRA_API_TOKEN` in the
environment take precedence if they are set. **Let the user type the token into the script's own
prompt — never ask them to paste it into the chat, and never echo it.**

Verify with real data:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/my_issues.py
```

It must print actual issues (or an honest empty result for a user with nothing assigned — in
that case verify instead with `get_issue.py <a-real-key>`).

Say explicitly which path ended up working: the rest of the workflow branches on it.

## Step 3: Slack (optional)

Only needed if this team wants the session to read threads or post to a project channel. Ask
whether to set it up; "skip" is fine and costs nothing later.

If yes, follow `${CLAUDE_PLUGIN_ROOT}/skills/slack/SETUP.md`. The short version:

1. Install the `agent-slack` CLI as that file describes.
2. `agent-slack auth import-desktop` — imports the session from the installed Slack desktop
   app, so no token is typed anywhere. A bot token in `SLACK_BOT_TOKEN` is the alternative.
3. Verify: `agent-slack auth test` must report the workspace and the authenticated user.

Ask for the workspace host (`your-org.slack.com`) and the project channel id (`C…`) — they go
into `slack.workspace` and `slack.projectChannel` in Step 5. A channel id is not a secret; a
token is. Do not put a token in `task-flow.json`.

## Step 4: browser automation

The `playwright` MCP server drives the live app in the verification step and in
`@critique-agent`. It launches its own Chromium, which has to be downloaded once.

1. `claude mcp list` — confirm `playwright` appears.
2. `npx playwright install chromium` — run it yourself and confirm it finished.
3. Verify the server: navigate to `https://example.com` with
   `mcp__playwright__browser_navigate` and report the page title.
4. If `mcp__playwright__*` tools are not present in the session at all, they load at session
   start: start a fresh session and re-check.

If the project serves local HTTPS with a self-signed certificate, expect a certificate warning
until the project's own local setup is done. Note it and move on.

## Step 5: this repository's `.claude/task-flow.json`

Everything project-specific lives in one file in the **consuming repo**, not in the plugin.
Start from the template and its field-by-field documentation:

- `${CLAUDE_PLUGIN_ROOT}/templates/task-flow.json` — the skeleton
- `${CLAUDE_PLUGIN_ROOT}/templates/task-flow.schema.md` — what every field means

If `.claude/task-flow.json` already exists, read it, show the user what it says, and offer to
fill the gaps rather than overwriting it.

**Interview for the values one at a time — one question per message, never a list.** Where the
plausible answers are enumerable, offer them so answering costs one word. Infer a default from
the repo where you honestly can (the base branch from `git symbolic-ref refs/remotes/origin/HEAD`,
the remote from `git remote`, test and lint commands from the `Makefile`, `package.json`
scripts, `pyproject.toml`, or CI config) and ask the user to confirm it rather than asking cold.

The order that works:

1. **Tracker** — `jira` or `none`. If `jira`: the site URL, the default project key, the board
   id, and the `cloudId` from Step 2a if you have it.
2. **Git** — base branch, remote, and `mode`: `push-to-main` (the team commits straight to the
   base branch) or `pr` (every change goes through a pull request). For `pr`, the branch prefix.
3. **Verify commands** — what proves a change is good. The global `verify.commands` list, plus
   `verify.byArea` for path prefixes with their own suite (a frontend directory's tests, a
   backend's pytest). Run each one you propose at least once so you know it exists and passes.
4. **App** — `app.start` (the one command that brings the stack up) and `app.urls` (the named
   surfaces `@critique-agent` and the verification step will drive).
5. **Rules** — path prefix → the repo's own rule files that must be read before touching that
   area. Skip if the repo has none.
6. **Hotspots** — files or directories where two parallel sessions colliding is expensive
   (shared routers, migration directories, lockfiles). The session board warns on these.
7. **Stack commands** — the commands that restart or destroy the local stack, so the board can
   ask before one session yanks it from under another.
8. **Reporting** — the language for ticket comments and the comment style.

Then write the file, show the user the whole thing, and let them correct it before you finish.
Only Slack channel ids, host names and command strings go in here; **no tokens, no cloud
secrets, no personal emails**. It is committed to their repo.

Finally, check whether the transition names in `statusMap` / `transitionIds` actually match the
project's workflow. With the MCP server:
`mcp__atlassian__getTransitionsForJiraIssue` on a real ticket. With the scripts, whatever
`${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/` offers for transitions. Guessed transition ids
fail silently at the worst moment.

## Step 6: verify the whole thing end to end

Three checks, all with real output:

1. **The session board sees this session:**

   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/hooks/board.py overview
   ```

   It must print at least this session, with its branch. If it prints nothing, the hooks were
   not loaded — check that the plugin is enabled (`claude plugin list`) and run
   `/reload-plugins`, or start a fresh session.

2. **The tracker answers on a real ticket** — `get_issue.py <a real key from this project>`, or
   `mcp__atlassian__getJiraIssue`. Ask the user for a key they know exists. Skipped when the
   tracker is `none`.

3. **The skills are loaded:** `/10c-dev:implement` resolves, and `@critique-agent` is listed by
   `/agents`. Skills and agents are read at session start; if the files exist but nothing
   resolves, run `/reload-plugins` or start a fresh session.

# Done

Tell the user the workflow is ready, then summarize in a short block:

- which tracker path is live (MCP, scripts, or none) and what that means for `/10c-dev:implement`
- whether Slack is connected
- whether browser verification is available
- what got written into `.claude/task-flow.json`, and that it should be committed
- what was skipped, and how to come back and add it

Then point at the next move: `/10c-dev:implement <TICKET-KEY>` to run the build cycle, or
`${CLAUDE_PLUGIN_ROOT}/docs/process.md` to read what the cycle actually does.
