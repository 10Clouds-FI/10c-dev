---
name: slack
description: >-
  Read and write Slack from a session through the `agent-slack` CLI, which acts as the user's own
  Slack account. Covers reading channels, DMs and threads, posting and editing messages, creating
  channels and inviting people, setting a channel topic, and a raw Web API escape hatch for
  anything the CLI lacks. Use whenever a task touches Slack: "read this thread", "post to
  #channel", "create a channel", "who is in this channel", "set the topic", "search Slack", or
  when a `*.slack.com` link or a `C…`/`D…`/`G…` id shows up. Not installed yet, or `auth test`
  failing? Read SETUP.md first — it is a one-time setup you can run yourself.
metadata:
  version: 1.0.0
  title_en: Slack
  summary_en: "Reads and writes Slack through the agent-slack CLI: channels, threads, DMs, messages, creating channels and inviting people."
  category: [communicators, connectors]
---

# slack

One CLI, one auth store, so a recipe that works in one session works in everybody's.

Not installed, or `agent-slack auth test` fails? **[SETUP.md](SETUP.md)** is the one-time setup,
written to be run unattended. It also states plainly what this tool does to get a token and what
that means — worth reading once before using it on a work workspace.

## Auth model, in one paragraph

`agent-slack` acts as **you**. It imports your existing Slack Desktop session (an `xoxc` token per
workspace plus the shared `xoxd` cookie) into the macOS Keychain under the service name
`agent-slack` — or, where there is no Keychain, into `~/.config/agent-slack/credentials.json`
(Windows and Linux). Every call reads from there, and the bundled scripts check both. There is no
shared team credential and no bot to invite: if you can do it in the Slack UI, the CLI can do it,
and anything you post is posted under your own name. A bot token is the exception — both scripts
fall back to `$SLACK_BOT_TOKEN` where there is no session at all, such as a container, and then
the post is made as the bot.

That has a direct consequence people get wrong: **there is no "the plugin has no Slack access".**
Your session is the access. What limits you is what your own Slack account is allowed to do.

## Configuration

| Key in `.claude/task-flow.json` | Meaning |
|---|---|
| `slack.workspace` | The workspace every call targets, e.g. `acme.slack.com` |
| `slack.projectChannel` | The channel id (`C…`) for this repo's updates — the `implement` skill offers to post a one-paragraph "what just shipped" note there after a change lands |

```json
{
  "slack": {
    "workspace": "acme.slack.com",
    "projectChannel": "C0123456789"
  }
}
```

The bundled scripts resolve the workspace as `--workspace` → `$SLACK_WORKSPACE` →
`slack.workspace` in `.claude/task-flow.json`, and exit 2 rather than guess. The `agent-slack` CLI
itself knows nothing about that file, so **pass `--workspace` explicitly on every CLI call**.

## Workspace selector — get this right first

Every `agent-slack` command takes `--workspace`. Three rules, each of which costs real time when
missed:

**It is a subcommand option, so it goes AFTER the subcommand and its arguments** — `agent-slack
user list --workspace acme.slack.com`, never `agent-slack --workspace … user list`. There is no
global option by that name, so in the global position the call dies `unknown option
'--workspace'` with exit 1 and nothing on stdout. Through a pipe that empty reads exactly like a
workspace with no match.

**Never pass a bare slug.** The selector is a substring match, so `acme` can match both
`acme.slack.com` and `acme-dev.slack.com` and the call dies ambiguous — or worse, silently picks
one. Always write the full `acme.slack.com` form.

**The CLI's own default workspace is whichever one it stored first**, which is not necessarily
where the work is. A full permalink URL is self-locating and needs no `--workspace`; a bare
channel id is not, and outside the default workspace fails `channel_not_found`, which reads like a
missing channel rather than a missing flag.

**A PERSON in the wrong workspace is worse, because nothing fails at all.** `user list` and `user
get` answer about whichever workspace they resolved and never say which one that was, so someone
who works in the other workspace is simply absent — no error, no `not_found`, just a clean empty
that reads as "this person is not in Slack". A second trap sits underneath: `user list` defaults
to `--limit 200` and caps each page at 1000 with a `next_cursor`, so an exactly-round user count
means you are reading one page, not the directory.

**Do not expect the CLI to stop you.** Its one assertion fires only when the input names a channel
by NAME, more than one workspace is configured, no `--workspace` was passed and no default is set.
Everything else — a channel id, `user list`, `user get` — falls back to the stored default with no
check at all. Setting a default only changes WHICH workspace is silently wrong.

## Reading

```bash
agent-slack message list C0123456789 --workspace acme.slack.com --limit 30
agent-slack message list "https://acme.slack.com/archives/C…/p178…"   # permalink: no --workspace needed
agent-slack search messages "release notes" --workspace acme.slack.com
agent-slack unreads --workspace acme.slack.com
```

**`message list <channel>` returns only root messages**, and reports `reply_count=0` even when
replies exist. A reply to something you posted is invisible from the channel root. To read a
thread, pass the thread's permalink instead of the channel id, or keep the channel id and add
`--thread-ts <ts>` — which is the cheaper route right after you post, because you already hold the
ts. The flag is `--thread-ts`, not `--thread`, and a composite `C…/178…` target fails as `Could
not resolve channel name`, which reads as a missing channel.

**`message list` and `search` do not return reactions.** When emoji are being used as status tags,
read them through the Web API escape hatch below (`conversations.history`), not the CLI.

## Sending

**One line, no formatting → the CLI. Anything with structure → `post_message.py`.** The dividing
line is whether the body has line breaks, links or mentions in it.

```bash
agent-slack message send C0123456789 "text" --workspace acme.slack.com
agent-slack message send C0123456789 "reply" --workspace acme.slack.com --thread-ts 1786550261.589009
agent-slack message edit C0123456789 "fixed text" --workspace acme.slack.com --ts 1786603541.971849
```

**Confirm the recipient and the exact text with a human before sending.** A send is visible to
everyone in the channel and cannot be unsent, only edited, and an edit leaves an "(edited)" mark.

**Trust the envelope, not the absence of noise.** `agent-slack` prints benign warnings on stderr
while the send succeeds. A send worked when the response carries `"ok": true` and a `ts`. If you
did not get that, **do not blind-retry** — the message may well have gone out. Read the channel
back first and look for it.

A body with apostrophes, backticks and shell-special characters is best written to a file and sent
as `"$(cat /tmp/body.txt)"`, which sidesteps quoting entirely.

## Posting anything structured — `post_message.py`

Write the body to a file in the usual mrkdwn (`*bold*`, `<url|label>`, `<@U…>`, `<#C…|name>`,
`• ` bullets), then:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slack/scripts/post_message.py" post \
  --channel C0… --body-file /tmp/update.txt --workspace acme.slack.com
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slack/scripts/post_message.py" update \
  --channel C0… --ts 1787315195.458709 --body-file /tmp/update.txt
python3 "${CLAUDE_PLUGIN_ROOT}/skills/slack/scripts/post_message.py" topic \
  --channel C0… --topic "ABC-123 https://…"
```

`--dry-run` prints the blocks and the link count without sending. `--thread-ts` replies into a
thread. `--workspace` may be omitted when `$SLACK_WORKSPACE` or `slack.workspace` is set. Only
python3 is needed — no `jq`, no Keychain, so it works on Windows and Linux too.

**Why not the obvious routes.** Each of the three fails differently, and only the third failure is
invisible until someone complains:

| Route | What breaks |
|---|---|
| `agent-slack message send "<text>"` | converts markdown to rich text and **strips every line break** — a structured post arrives as one paragraph |
| `agent-slack message send --blocks` with `section` blocks | newlines and links survive, but **the author cannot edit their own post** from the Slack UI |
| raw `text` through `slack_api.sh chat.postMessage` | renders and stays editable, but caps at **3000 characters**, and `chat.update` on the same text leaves `<url\|label>` literal |

The reason for the middle row is worth carrying: Slack offers "Edit message" only when the content
round-trips into the composer, which means plain `text` or a `rich_text` block. A `section` block
has no such representation, so the post is frozen for its own author. `post_message.py` builds the
`rich_text` block itself — real `link`, `user` and `channel` elements, bold as a style — which
renders, stays editable, and has no 3000-character ceiling (verified at 3930).

**Verify the blocks, not the `text` field.** When a message carries explicit blocks, Slack keeps
`text` only as a notification fallback and normalizes it, so its newline count means nothing. Read
the message back and check that `blocks[].type` is `rich_text` and the `link` elements are there.

## Channel admin

```bash
agent-slack channel new    --name "project-kickoff" --workspace acme.slack.com   # → .id
agent-slack channel invite --channel C0… --users "U07…,U07…" --workspace acme.slack.com
agent-slack channel list   --workspace acme.slack.com
agent-slack user dm-open   U07… --workspace acme.slack.com                       # → .dm_channel_id (D…)
```

`channel new` takes `--private`; public is the default. The creator is added automatically.
`invite` takes user **ids**, and a bot is invited exactly like a person.

**Resolving a person to a `U…` id needs a list-and-filter.** `user get` accepts only a `U…` id or
an `@handle` — not a real name, not an email — and there is no `user search` subcommand:

```bash
agent-slack user list --workspace acme.slack.com --limit 500 \
  | jq -r '.users[] | select(.profile.email=="dev@example.com") | "\(.id)\t\(.real_name)"'
```

**Do not assume Slack's native JSON keys.** `user list` returns `{next_cursor, users}`, so iterate
`.users[]` and not `.members[]`. `channel list` entries can carry a **null** `name` (group DMs), so
`select(.name != null)` before any `.name | test(...)` or the filter crashes.

**A DM needs `dm-open` first.** Sending to a bare handle treats it as a channel name and dies
`Could not resolve channel name: #<handle>`. Open the DM, then send to the `D…` id.

## Raw Web API escape hatch

For any method the CLI has no command for — `conversations.setTopic`, `conversations.setPurpose`,
`reactions.add`, `conversations.history` with reactions — go through the bundled helper rather than
rebuilding the auth scaffolding inline:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/skills/slack/scripts/slack_api.sh" conversations.setTopic \
  --workspace acme.slack.com -d channel=C0… -d "topic=ABC-123 https://…"
```

Shape: `slack_api.sh <method> [--workspace <ws>] [--as-bot] [-d key=value]...`. Raw JSON on stdout,
exit 0 on `ok:true`, exit 1 on `ok:false` with `.error` named on stderr, exit 2 on missing
credentials or no workspace. `--as-bot` uses `$SLACK_BOT_TOKEN` instead of your session — only
where a service identity is genuinely wanted, and only where that app has been invited to the
channel, or the call dies `not_in_channel`.

**It needs `jq`**, and says so rather than failing obscurely. If `jq` is not there and you only
need to post, edit or set a topic, use `post_message.py` above — it needs only python3.

It carries two auth details that are expensive to rediscover: the `xoxd` cookie **must** be
URL-encoded or every call fails `invalid_auth`, and the `xoxc` token goes in the `token=` form
field, never as an `Authorization: Bearer` header.

**`setTopic` and `setPurpose` answer `ok:true` with the field echoed as `null` even on success.**
That null is not a failure and not a reason to retry the write. Confirm with one
`conversations.info` read.

## Formatting gotchas

Slack's markup is mrkdwn, not Markdown: `*bold*` with single asterisks, `_italic_`, `~strike~`.

**A bare domain or URL inside inline backticks breaks the code span.** Slack's autolinker rewrites
it into a link, which eats the closing backtick, so the tail of your command falls out of the code
formatting and renders as a hyperlink in running text. Put any command containing a URL or a
hostname in a **fenced block** instead, where the renderer suppresses the link. The stored source
text still shows `<http://…|…>` when you read the message back through the API, and that is
expected — do not "fix" a message that already displays correctly.

**Attaching a file downgrades the message to plain text** — `@mentions` stop pinging and `*bold*`
shows literally. Post the text and the file separately when the formatting matters.

**Several `--attach` flags on one `message send` produce several messages.** The text goes out with
the first file, and every further file lands as its own message right below it. To edit the post or
reply in its thread later, pick the message that actually holds the file you mean.

## Common failures

| Symptom | Cause |
|---|---|
| `channel_not_found` on a real channel | `--workspace` missing or wrong; a bare id is not self-locating |
| ambiguous workspace | a bare slug matched two workspaces; use the full `acme.slack.com` |
| `error: unknown option '--workspace'`, empty stdout, exit 1 | the flag is before the subcommand; it goes after it |
| `not_in_channel` | you are posting under a bot identity that was never invited; use your own session |
| `invalid_auth` on every call | the `xoxc` token rotated (it does when you re-log Slack). Re-run the import from SETUP.md |
| `Could not resolve channel name: #jane.doe` | that is a person; `dm-open` first |
| `no workspace` from a bundled script | set `slack.workspace` in `.claude/task-flow.json`, `$SLACK_WORKSPACE`, or pass `--workspace` |
| CLI missing entirely | SETUP.md, step 1 |
