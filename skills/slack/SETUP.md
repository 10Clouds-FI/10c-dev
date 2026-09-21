# slack — SETUP (read this first if `agent-slack` is not working yet)

[SKILL.md](SKILL.md) is how to *use* Slack from a session. **This file is the one-time setup.**

> **If you are Claude Code reading this:** you can run every step below yourself. The only things
> you need from the human are that they are **logged into Slack Desktop** on this machine, and
> that they have read "What this actually does" before you import anything.

---

## What this actually does — read this before step 2

`agent-slack` does not use a Slack app or a bot token. It reads the session token out of the
**local Slack Desktop data** and calls Slack's Web API as you.

Three things follow, and whoever runs this should know all three:

- **Everything is done under your own name.** Messages you post are your messages; channels you create list you as creator. There is no service identity absorbing the blame or the credit.
- **This is outside Slack's supported automation path.** The supported path is a Slack app with a bot token. Extracting a token from the desktop client is not, and Slack's security tooling can raise an alert to your workspace admins.
- **The token is as sensitive as your password.** It sits in the macOS Keychain, the same place Safari keeps saved passwords. Never paste it into a file, a repo, a ticket or a chat.

If you are not comfortable with the second point, stop here and say so rather than running the
import quietly. Asking a workspace admin first costs nothing.

## 0. What it needs

| Thing | Required? | Why |
|---|---|---|
| **Node.js** | yes | `agent-slack` installs from npm |
| **Slack Desktop, logged in** | yes | The import reads its local session |
| **macOS** | for `import-desktop` as written below | That import path is macOS-only; see the Windows/Linux note under step 2 |
| **`jq`** | only for the escape hatch | `scripts/slack_api.sh` uses it and exits 2 naming it. `scripts/post_message.py` needs nothing but python3 |

## 1. Install the CLI

```sh
npm i -g agent-slack
agent-slack --version
```

## 2. Import your Slack session

Slack Desktop can stay open.

```sh
agent-slack auth import-desktop
```

If that finds nothing, import from a logged-in browser tab instead:

```sh
agent-slack auth import-chrome     # or: import-brave / import-firefox
```

Last resort, when neither works: open Slack in a browser, copy any request to `slack.com/api/…`
from DevTools as cURL, then run `agent-slack auth parse-curl` and paste it.

**Windows and Linux** have no Keychain. The same session lives in
`~/.config/agent-slack/credentials.json` (`%APPDATA%\agent-slack\credentials.json` on Windows),
and both bundled scripts read the Keychain first and that file second, so nothing else changes.

## 3. Verify

```sh
agent-slack auth whoami
agent-slack auth test --workspace acme.slack.com
```

`whoami` lists the workspaces it picked up and masks the tokens. `auth test` should answer `ok`
with your handle. Check that the workspace you actually work in is in the list.

## 4. Configure the workspace once

So that no call has to guess, put it in the repo's `.claude/task-flow.json`:

```json
{
  "slack": {
    "workspace": "acme.slack.com",
    "projectChannel": "C0123456789"
  }
}
```

`$SLACK_WORKSPACE` does the same job for a machine that works in one workspace across repos.

## 5. Smoke test

Read something you already have access to. Do not smoke-test by posting.

```sh
agent-slack channel list --workspace acme.slack.com --limit 5
```

JSON with channels in it means you are done. Go to [SKILL.md](SKILL.md).

---

## Common failure modes

- **`agent-slack: command not found`** → step 1 did not run, or the npm global bin is not on PATH (`npm bin -g` says where it went).
- **`import-desktop` finds nothing** → Slack Desktop has never been logged in here, or this is a managed device that encrypts its data directory. Use `import-chrome`.
- **`invalid_auth` on everything, having worked before** → the `xoxc` token rotated, which happens when you re-log into Slack. Re-run step 2; nothing else needs changing.
- **`ambiguous workspace`** → the selector is a substring match and matched more than one workspace. Pass the full `acme.slack.com` form, never a bare slug.
- **`error: unknown option '--workspace'`** → the flag is before the subcommand. It is a subcommand option, so it goes after the subcommand and its arguments. Worth recognising by sight: the failure is exit 1 with empty stdout, which through a pipe reads like a genuinely empty result.
- **`channel_not_found` on a channel you can see** → no `--workspace`, or the wrong one. A bare channel id is only meaningful inside one workspace.

## When a bot token is the right answer instead

Use a Slack app with a bot token, not this, when the thing posting should **not** be a person: an
unattended service, a recurring automated post, anything where "who sent this" should read as the
system rather than as you. Both bundled scripts fall back to `$SLACK_BOT_TOKEN` when no session is
present, which is also how they work inside a container with no Slack Desktop to import from. This
skill's baseline, though, is work you are doing yourself, with your own session behind it.
