#!/usr/bin/env python3
"""post_message.py - post or edit a Slack message that renders AND stays editable.

    python3 post_message.py post   --channel C0… --body-file msg.txt [--thread-ts …]
    python3 post_message.py update --channel C0… --ts 178… --body-file msg.txt
    python3 post_message.py topic  --channel C0… --topic "ABC-123 https://…"
    python3 post_message.py post   --channel C0… --body-file msg.txt --dry-run

The workspace comes from --workspace, else $SLACK_WORKSPACE, else slack.workspace
in the repo's .claude/task-flow.json; with none of those the script exits 2 rather
than guessing, because a Slack id is only meaningful inside one workspace.

Why this exists rather than `agent-slack message send` or slack_api.sh chat.postMessage.
Three routes, three different ways of being wrong:

  * `agent-slack message send "<text>"` converts markdown to rich text and STRIPS
    EVERY LINE BREAK. A structured kickoff arrives as one paragraph.
  * `agent-slack message send --blocks` with `section` blocks keeps the newlines and
    renders links, but the author CANNOT EDIT THE POST from the Slack UI. Slack only
    offers "Edit message" when the content round-trips into the composer, i.e. plain
    `text` or a `rich_text` block. A `section` block has no such representation.
  * raw `text` to chat.postMessage renders and stays editable, but Slack converts it
    to a rich_text block whose limit is 3000 CHARACTERS, not the 4000 the message
    limit suggests - and chat.update on the same text does NOT parse `<url|label>`,
    so links come out literal.

So this script builds the `rich_text` block itself: real `link`, `user` and `channel`
elements, bold as a style rather than asterisks. Links render, mentions ping, the
author can edit, newlines survive, and the 3000-char ceiling does not apply.

Input is a FILE, not an argument, so newlines and quoting survive the shell. Write the
body in the same mrkdwn the templates use: `*bold*`, `<url|label>`, `<@U…>`, `<#C…|name>`,
`• ` bullets.

Credentials come from whatever agent-slack already has - macOS Keychain first, then
~/.config/agent-slack/credentials.json (Windows and Linux keep them there). Identity is
YOU, exactly like the rest of the CLI. See ../SETUP.md. Where there is no session at all
(a container), $SLACK_BOT_TOKEN is used instead and the post is made as the bot.

Exit 0 on ok:true, 1 on ok:false (Slack's .error on stderr), 2 on bad usage or no
credentials.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request

TASK_FLOW_RELPATH = os.path.join(".claude", "task-flow.json")

# A Windows console defaults to cp1250 here, and Slack bodies carry emoji. Without this
# the script dies UnicodeEncodeError while PRINTING THE RESPONSE - i.e. after the
# message has already gone out, which reads as a failure and invites a double post.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # already wrapped, or not a real tty
        pass

# ---------------------------------------------------------------------- workspace


def task_flow_slack(start=None):
    """The `slack` section of the repo's .claude/task-flow.json, or {}.

    Found by walking up from the working directory. A missing or malformed file
    is treated as absent: it is optional config in somebody else's repo.
    """
    directory = os.path.abspath(start or os.getcwd())
    while True:
        candidate = os.path.join(directory, TASK_FLOW_RELPATH)
        if os.path.isfile(candidate):
            try:
                with open(candidate, encoding="utf-8") as fh:
                    cfg = json.load(fh)
            except (OSError, ValueError):
                return {}
            section = cfg.get("slack") if isinstance(cfg, dict) else None
            return section if isinstance(section, dict) else {}
        parent = os.path.dirname(directory)
        if parent == directory:
            return {}
        directory = parent


def normalize_workspace(value):
    """`acme` / `acme.slack.com` / `https://acme.slack.com/…` -> `acme.slack.com`."""
    if not value:
        return None
    ws = value.strip().replace("https://", "").replace("http://", "").split("/")[0]
    if not ws:
        return None
    if "." not in ws:
        ws += ".slack.com"
    return ws


def resolve_workspace(explicit):
    for candidate in (explicit,
                      os.environ.get("SLACK_WORKSPACE"),
                      task_flow_slack().get("workspace")):
        ws = normalize_workspace(candidate)
        if ws:
            return ws
    sys.exit("post_message: no workspace. Pass --workspace <name>.slack.com, set "
             "$SLACK_WORKSPACE, or add {\"slack\": {\"workspace\": \"...\"}} to "
             ".claude/task-flow.json.")


# --------------------------------------------------------------------------- auth


def _keychain(account):
    try:
        out = subprocess.run(
            ["security", "find-generic-password", "-s", "agent-slack", "-a", account, "-w"],
            capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def _cred_files():
    seen, paths = set(), []
    for base in (os.environ.get("XDG_CONFIG_HOME"),
                 os.path.join(os.path.expanduser("~"), ".config"),
                 os.environ.get("APPDATA")):
        if not base:
            continue
        p = os.path.join(base, "agent-slack", "credentials.json")
        if p not in seen:
            seen.add(p)
            paths.append(p)
    return paths


def credentials(workspace):
    """(xoxc, xoxd) for a workspace, from the Keychain or the on-disk store."""
    xoxc = _keychain("xoxc:https://%s" % workspace)
    xoxd = _keychain("xoxd")
    if xoxc and xoxd:
        return xoxc, xoxd

    for path in _cred_files():
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
        for ws in cfg.get("workspaces", []):
            # Substring match, same as the CLI. Pass the full "acme.slack.com"
            # form: a bare slug can be a substring of a second workspace's URL,
            # and then the wrong workspace is selected silently.
            if workspace in ws.get("workspace_url", ""):
                auth = ws.get("auth", {})
                if auth.get("xoxc_token") and auth.get("xoxd_cookie"):
                    return auth["xoxc_token"], auth["xoxd_cookie"]

    # No session anywhere. $SLACK_BOT_TOKEN is the fallback credential, and in a
    # container with no Slack Desktop to import from it is the only one there is.
    bot = os.environ.get("SLACK_BOT_TOKEN")
    if bot:
        return bot, None

    sys.exit("post_message: no agent-slack session for %s and no $SLACK_BOT_TOKEN - run "
             "the import in %s/../SETUP.md or set the token"
             % (workspace, os.path.dirname(os.path.abspath(__file__))))


def call(workspace, method, params):
    token, xoxd = credentials(workspace)
    headers = {
        "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
        "User-Agent": "Mozilla/5.0",
    }
    if xoxd is None:
        # A bot token goes as a bearer, and only as a bearer.
        headers["Authorization"] = "Bearer " + token
        body = urllib.parse.urlencode(params).encode()
    else:
        # The cookie MUST be URL-encoded and the token MUST travel as a form
        # field; an Authorization: Bearer header fails invalid_auth for xoxc.
        headers["Cookie"] = "d=" + urllib.parse.quote(xoxd, safe="")
        body = urllib.parse.urlencode(dict(params, token=token)).encode()
    req = urllib.request.Request(
        "https://%s/api/%s" % (workspace, method), data=body, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())


# ------------------------------------------------------------------ mrkdwn parsing

TOKEN = re.compile(
    r'<(?P<url>https?://[^|>]+)\|(?P<label>[^>]+)>'
    r'|<(?P<bare>https?://[^>]+)>'
    r'|<@(?P<user>[UW][A-Z0-9]+)(?:\|[^>]*)?>'
    r'|<#(?P<chan>C[A-Z0-9]+)(?:\|[^>]*)?>'
)
SPAN = re.compile(r'\*[^*\n]+\*|`[^`\n]+`')


def _styled(text, inherited=None):
    """Split a link-free run into text elements, honouring *bold* and `code`.

    The two NEST: `*a `b` c*` yields a bold run, a bold+code run and a bold run,
    because Slack's rich_text style object carries both flags at once. Whichever
    span OPENS first wins, so asterisks inside `code` stay literal and backticks
    inside *bold* still become code. Before 2026-09-03 this scanned bold and code
    as plain alternatives and gave each match a single style, so an outer *bold*
    swallowed the backticks in `*release: `some-package` 0.38.1*` and shipped them
    as visible characters into the channel.
    """
    out = []
    pos = 0
    for m in SPAN.finditer(text):
        if m.start() > pos:
            out.append({"type": "text", "text": text[pos:m.start()]})
        raw = m.group(0)
        inner = raw[1:-1]
        if raw[0] == '*':
            out.extend(_styled(inner, {"bold": True}))
        else:
            out.append({"type": "text", "text": inner, "style": {"code": True}})
        pos = m.end()
    if pos < len(text):
        out.append({"type": "text", "text": text[pos:]})
    if inherited:
        for e in out:
            e["style"] = dict(inherited, **e.get("style", {}))
    return [e for e in out if e["text"]]


def to_elements(text):
    out, pos = [], 0
    for m in TOKEN.finditer(text):
        if m.start() > pos:
            out.extend(_styled(text[pos:m.start()]))
        if m.group('url'):
            out.append({"type": "link", "url": m.group('url'), "text": m.group('label')})
        elif m.group('bare'):
            out.append({"type": "link", "url": m.group('bare')})
        elif m.group('user'):
            out.append({"type": "user", "user_id": m.group('user')})
        else:
            out.append({"type": "channel", "channel_id": m.group('chan')})
        pos = m.end()
    if pos < len(text):
        out.extend(_styled(text[pos:]))
    return out


def to_blocks(text):
    return [{"type": "rich_text",
             "elements": [{"type": "rich_text_section",
                           "elements": to_elements(text.rstrip('\n'))}]}]


def fallback_text(text):
    """Plain-text twin for notifications and search: strip the link syntax."""
    return re.sub(r'<([^|>]+)\|([^>]+)>', r'\2', text.rstrip('\n'))


# ------------------------------------------------------------------------- report


def _report(result, method):
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        sys.stderr.write("post_message: %s -> ok:false (%s)\n"
                         % (method, result.get("error", "unparseable response")))
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["post", "update", "topic"])
    ap.add_argument("--channel", required=True, help="C…/D…/G… id")
    ap.add_argument("--body-file", help="file holding the mrkdwn body (post/update)")
    ap.add_argument("--ts", help="message ts to edit (update)")
    ap.add_argument("--thread-ts", help="reply into this thread (post)")
    ap.add_argument("--topic", help="topic text (topic)")
    ap.add_argument("--workspace",
                    help="e.g. acme.slack.com; default $SLACK_WORKSPACE, then "
                         "slack.workspace in .claude/task-flow.json")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the blocks that would be sent and exit")
    args = ap.parse_args()

    ws = resolve_workspace(args.workspace)

    if args.action == "topic":
        if not args.topic:
            ap.error("topic needs --topic")
        rc = _report(call(ws, "conversations.setTopic",
                          {"channel": args.channel, "topic": args.topic}),
                     "conversations.setTopic")
        # setTopic echoes topic:null even on success; confirm with a read instead of
        # retrying the write.
        if rc == 0:
            info = call(ws, "conversations.info", {"channel": args.channel})
            sys.stderr.write("topic now: %s\n"
                             % info.get("channel", {}).get("topic", {}).get("value"))
        return rc

    if not args.body_file:
        ap.error("%s needs --body-file" % args.action)
    with open(args.body_file, encoding="utf-8") as fh:
        text = fh.read()
    blocks = to_blocks(text)

    if args.dry_run:
        print(json.dumps(blocks, ensure_ascii=False, indent=2))
        n = sum(1 for e in blocks[0]["elements"][0]["elements"] if e["type"] == "link")
        sys.stderr.write("dry run: %d chars, %d newlines, %d link elements\n"
                         % (len(text), text.count("\n"), n))
        return 0

    params = {"channel": args.channel,
              "text": fallback_text(text),
              "blocks": json.dumps(blocks, ensure_ascii=False)}
    if args.action == "post":
        if args.thread_ts:
            params["thread_ts"] = args.thread_ts
        return _report(call(ws, "chat.postMessage", params), "chat.postMessage")

    if not args.ts:
        ap.error("update needs --ts")
    params["ts"] = args.ts
    return _report(call(ws, "chat.update", params), "chat.update")


if __name__ == "__main__":
    sys.exit(main())
