<p align="center">
  <img src="docs/assets/hero.svg" alt="10Clouds — 10c-dev, the delivery workflow for Claude Code" width="900">
</p>

<p align="center">
  <img alt="License MIT" src="https://img.shields.io/badge/license-MIT-081735?style=flat-square">
  <img alt="Version 0.2.0" src="https://img.shields.io/badge/version-0.2.0-152E61?style=flat-square">
  <img alt="Claude Code plugin" src="https://img.shields.io/badge/Claude%20Code-plugin-29555E?style=flat-square">
</p>

```
/plugin marketplace add 10Clouds-FI/10c-dev
/plugin install 10c-dev@10c-dev
```

## Why

Agentic coding fails in repeatable ways: guessing instead of asking, building a cathedral when a
shed was asked for, testing what it built instead of what was asked, calling it done because it
compiled, and parallel sessions pushing each other's half-finished commits. This plugin encodes the process that closes each of those, and knows
nothing about your stack: everything project-specific is one file in your repository.

## What it does

<p align="center">
  <img src="docs/assets/cycle.svg" alt="The 10c-dev process: a ticket and the project model feed Build (rung, interview, spec, tests first, code), then verify on the running app, a code review agent, cleanup, a critic that is mandatory on risky or core changes, and a commit that waits for your yes; CI unit tests gate staging, CI e2e tests gate production, and a human check on production is what turns the ticket Done" width="560">
</p>

Every change that reaches `main` starts from a ticket. When work starts in a Slack thread or a
client message, the agent drafts the ticket, you agree it, and it is created before any code. A
synthetic `LOCAL-<date>-<time>` key exists only for local R0/R1 work, which never reaches `main`.
The session reads the project model, then states a **rung**: R0 probe, R1 PoC, R2 MVP, R3
hardened. It defaults to the lowest one that answers the request and climbs only with your
agreement. Only R2 and R3 go to `main`.

It then **interviews** you one question per message until the goal can be stated without hedging,
and posts a **Spec** in the chat: goal, out of scope, a plan with a check per step, and two to
four "done when" conditions written as what a user would observe. **Tests first:** a separate
test-design agent turns those conditions into unit and end-to-end tests before any code exists.
Then the code is written, with the area rules loaded, and proved on the running app rather than
on a green compile. A **Code review** agent that never saw the build reads the diff, and a
cleanup pass follows. For risky changes, and for changes near a core capability, a **Critic**
starting from an empty context then drives the live app and returns PASS or FAIL; a FAIL goes
back to the build. It commits only on your yes, under your name, to `main` or, when a change needs a
second pair of eyes, as a pull request.

The ticket status is derived from where the code is, never from how the conversation went:
**In Progress** while it is local, **In Review** once it is on staging after a green CI,
**Done** only after a human checked it in production (`/10c-dev:release-check`). Longer version:
[`docs/process.md`](docs/process.md).

<details>
<summary>The questions a first look usually raises</summary>

- **Is this all ceremony for a typo fix?** No. The rung decides how much process runs, and R0
  and R1 are for throwaway work that stays local. A one-line fix that ships is R2 with a small
  ceremony: one interview question, one reproducing or main-path test, a short review. Only R2
  and R3 reach `main`.
- **Does it assume Jira and a release train?** No. The tracker, its status names, the base
  branch, push-to-main versus pull requests, and how to start the app all come from
  `.claude/task-flow.json` in your repo. Any tracker works, but a change to `main` needs a ticket:
  `"tracker": "none"` and `LOCAL-` keys are for local R0/R1 work only. If you deploy
  continuously, "checked on production" is simply the step after your deploy.
- **What does it do without asking?** It edits your working tree, runs your app locally, and
  moves the ticket to In Progress when you name a key and to In Review once the change is on
  staging. It never commits, pushes, posts to Slack, or marks a ticket Done without your yes in
  the conversation.
- **Does it work in a branch?** It works in your checkout. By default it commits to the base
  branch, which is how teams that deploy `main` to staging run it; for any single change you can
  ask for a pull request instead, and `"git": {"mode": "pr"}` makes that the default. Either way
  the shared board warns when another live session on the machine holds the same files.
- **Is any of it enforced, or is it just prose?** Mostly prose the model follows, plus mechanical
  guards in the shared board hooks: you are asked before an edit to a file a neighbour is
  editing, before a stack restart a neighbour is testing against, and before a push that would
  carry another session's commits. Risky changes are also checked at push time for a recorded
  critic PASS. Nothing is committed or pushed without your explicit yes in the conversation.
- **Why does the critic not read the code?** So it tests what was asked for rather than what was
  built. It gets the ticket, the "done when" conditions and the running app, drives it like a
  user, and reports PASS or FAIL. It is mandatory for risky changes (tenant isolation,
  authorization, migrations, pipelines, a chat gateway: the list is yours to configure) and for
  changes near a core capability; for the rest, you decide.
- **Why a separate agent for tests and for review?** An agent that writes tests for its own code
  tends to test what it built, and one that reviews its own diff tends to approve it. Tests are
  designed first from the "done when" conditions by an agent that never writes the code, and the
  review is done by an agent that never saw how the task was solved.
- **What does it send where?** Only what you already use: calls to your Jira site with your own
  token, and Slack posts you approve one by one. There is no telemetry and no third-party
  service of ours in the loop.

</details>

## Skills

| Command | What it does |
|---|---|
| `/10c-dev:setup` | One-time machine and repo onboarding; writes `.claude/task-flow.json` |
| `/10c-dev:implement` | The full cycle above for one ticket, from drafting the ticket to the push |
| `/10c-dev:coding` | The build phases on their own: rung, interview, spec, tests first, code |
| `/10c-dev:code-review` | Review of a diff, branch or PR, with a severity-ranked verdict |
| `/10c-dev:release-check` | The production check: walks you through it, then Done, or a new ticket for a bug |
| `/10c-dev:cleanup` | What did this change make pointless — remove the obvious, propose the rest |
| `/10c-dev:project-model` | A map of what each part of the codebase is *for* |
| `/10c-dev:jira` | Read and move tickets: JQL search, issue detail, comment, transition, board |
| `/10c-dev:slack` | Read and post in Slack through the `agent-slack` CLI |

Most of these also fire on their own when the task calls for them; `implement` is the one you
invoke by name. Three agents do the independent work:

- `@test-design-agent` writes the unit and end-to-end tests from the "done when" conditions
  before any code exists. It never writes the implementation.
- `@code-review-agent` reads the diff in a fresh context and ranks findings from blocker to nit.
  Blockers and majors are fixed before the commit; minors and nits are fixed now when the file is
  already in the diff, otherwise they go in a comment on the ticket.
- `@critique-agent` (the Critic) reads the ticket and the "done when" conditions, never the
  source, drives the live app through at least five scenarios trying to break it, and returns
  PASS or FAIL. Mandatory on risky changes or near a core capability.

### Connectors

<img src="https://img.shields.io/badge/Jira-081735?style=flat-square&logo=jira&logoColor=white" alt="Jira"> —
reads tickets, moves them between statuses, and comments on them. Either the `atlassian` MCP
server this plugin declares (OAuth in the browser, per user, nothing stored in the repo) or an API
token for the bundled scripts. Set `"tracker": "none"` to run the workflow with no tracker at all.

<img src="https://img.shields.io/badge/Slack-081735?style=flat-square&logo=slack&logoColor=white" alt="Slack"> —
reads channels, DMs and threads and posts messages, so a session can send a heads-up before a
risky push. It runs through the `agent-slack` CLI, which reuses the session from your Slack desktop
app, so no token is typed anywhere. Optional; nothing in the cycle depends on it.

## Install

Both routes are verified on this plugin — hooks, MCP servers, agents and skills all load. The
marketplace route is the two commands at the top, run inside Claude Code; the repository is its own
marketplace, so both names are `10c-dev`. Then run `/10c-dev:setup` once.

<details>
<summary>From a shell, or clone-and-symlink to edit the workflow as you use it</summary>

```bash
claude plugin marketplace add 10Clouds-FI/10c-dev
claude plugin install 10c-dev@10c-dev
```

```bash
git clone https://github.com/10Clouds-FI/10c-dev.git ~/src/10c-dev
cd ~/src/10c-dev && ln -sfn "$PWD" ~/.claude/skills/10c-dev
```

The symlinked copy loads on the next session as `10c-dev@skills-dir` with no install step,
including the hooks and the two MCP servers. Edits to a `SKILL.md` take effect immediately;
changes to `hooks/`, `.mcp.json` or `agents/` need `/reload-plugins` or a fresh session.

Either way, confirm with `claude plugin list` and `claude plugin details 10c-dev`.

**Updating:** `claude plugin marketplace update 10c-dev`. Installed copies pick up a new version
when `version` in `.claude-plugin/plugin.json` changes; a symlinked clone updates with `git pull`
plus `/reload-plugins`.

</details>

`/10c-dev:setup` walks a machine and a repository through setup one step at a time, verifying each
step with real output: runtimes, the ticket tracker, Slack, the Playwright browser, then an
interview that writes this repo's config, and an end-to-end check on a real ticket.

## Configuration

One file in your repository, committed: `.claude/task-flow.json`. `/10c-dev:setup` writes it by
interview; [`templates/task-flow.schema.md`](templates/task-flow.schema.md) documents every field.

```json
{
  "tracker": "jira",
  "jira": { "site": "https://your-org.atlassian.net", "projectKey": "ABC" },
  "git": { "baseBranch": "main", "mode": "main", "branchPrefix": "feature/" },
  "verify": { "commands": ["make lint"], "byArea": { "src/web": ["npm test"] } },
  "app": { "start": "make start", "urls": { "app": "http://localhost:3000/" } },
  "rules": { "src/web": [".claude/rules/frontend.md"] }
}
```

<details>
<summary>The rest of the config, and where credentials live</summary>

`risky` lists the paths and labels that make a change risky (the critic is then mandatory),
`owners` maps paths to the person who must approve a contract break (or defers to CODEOWNERS),
`ci` tells the plugin how to read the unit and e2e runs, the staging and production URLs, and
`verify.e2e` is the local end-to-end command. `hotspots` names the paths where two sessions
colliding is expensive, and `reporting` sets the language and tone of ticket comments.
`tracker: "none"` is valid for local R0/R1 work on synthetic `LOCAL-<date>-<time>` keys, which
cannot be pushed to `main`.

**No credentials go in that file** — it is committed to your repository.

- **Jira** — either the `atlassian` MCP server (OAuth in the browser, per user), or
  `JIRA_EMAIL` / `JIRA_API_TOKEN` in the environment, or `python3 skills/jira/scripts/setup.py`,
  which stores them under `$CLAUDE_PLUGIN_DATA/jira/credentials.json`, outside the repository.
- **Slack** — `agent-slack auth import-desktop` reuses the session from the Slack desktop app, so
  no token is typed anywhere. `SLACK_BOT_TOKEN` is the alternative. See
  [`skills/slack/SETUP.md`](skills/slack/SETUP.md).
- **Playwright** — no credentials; `npx playwright install chromium` once.

</details>

## The shared board

Several sessions on one machine, often on one checkout, is the normal case and the usual source of
expensive accidents. Hooks maintain a board under `~/.claude/10c-dev/board/`, one JSON file per
live session, and feed each session a digest of its neighbours: who is here, which ticket, which
phase, which branch, which files, and whether it is using the local stack. The hooks warn
**before** an edit to a file a neighbour is editing, before a restart of a **local stack** a
neighbour is testing against (a session is marked as using the stack automatically when it starts
it or drives the browser), and before a **push** that would carry commits belonging to another
session. They also load the area rules for a file before its first edit, raise a blocker on the
**hotspots** you listed, and ask before pushing a risky change with no recorded critic PASS. The
checks run as hooks, so a session cannot skip them by not looking.

```bash
python3 "$CLAUDE_PLUGIN_ROOT/hooks/board.py" overview   # live sessions on this repo
python3 "$CLAUDE_PLUGIN_ROOT/hooks/board.py" overlap    # files you and a neighbour both touch
```

More in [`hooks/README.md`](hooks/README.md).

## Contributing

Tests, manifest validation and the no-internal-identifiers check are in
[`CONTRIBUTING.md`](CONTRIBUTING.md). `claude --plugin-dir .` loads the working copy for a session,
ahead of any installed copy.

## License

MIT — see [`LICENSE`](LICENSE).
