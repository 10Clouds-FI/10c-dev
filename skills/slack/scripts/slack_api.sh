#!/usr/bin/env bash
# slack_api.sh — call any Slack Web API method with the credentials agent-slack already holds.
#
#   bash slack_api.sh <method> [--workspace <ws>] [--as-bot] [-d key=value]...
#
# For the methods agent-slack has no command for: conversations.setTopic / setPurpose,
# reactions.add, conversations.history when you need reactions. If agent-slack HAS a
# command for it, use the command — see ../SKILL.md.
#
# Examples:
#   bash slack_api.sh auth.test --workspace acme.slack.com
#   bash slack_api.sh conversations.setTopic --workspace acme.slack.com \
#        -d channel=C0… -d "topic=ABC-123 https://…"
#   bash slack_api.sh conversations.history --workspace acme.slack.com \
#        -d channel=C0… -d limit=50 | jq '.messages[] | select(.reactions!=null)'
#
# IDENTITY. Default is YOU: the xoxc/xoxd session agent-slack imported (see ../SETUP.md),
# read from the macOS Keychain, or from ~/.config/agent-slack/credentials.json where there
# is no Keychain — Windows and Linux. Pass --as-bot to use a bot token from $SLACK_BOT_TOKEN
# instead — only where a service identity is actually wanted, and only where that app
# has been invited to the channel, or the call dies not_in_channel.
#
# NOT FOR POSTING. chat.postMessage through here sends raw text, which Slack caps at the
# 3000 characters of the rich_text block it converts to, and chat.update does not parse
# <url|label> at all. Use scripts/post_message.py for anything you post or edit.
#
# WORKSPACE. Takes a slug or a URL (acme | acme.slack.com | https://acme.slack.com).
# Resolved from --workspace, else $SLACK_WORKSPACE, else slack.workspace in the repo's
# .claude/task-flow.json; with none of those the script exits 2 rather than guessing.
# Channel ids are workspace-scoped, so the wrong workspace dies channel_not_found — and
# pass the full "acme.slack.com" form, since a bare slug can be a substring of a second
# workspace's URL and would select it silently.
#
# OUTPUT. Raw JSON on stdout (pipe to jq). Exit 0 on ok:true; exit 1 on ok:false (the
# JSON is still printed, .error named on stderr); exit 2 on missing credentials or bad
# usage.
#
# Auth details embodied here — do not re-derive them inline: the xoxd cookie MUST be
# URL-encoded or every call fails invalid_auth, and the xoxc token goes as the form
# field token=, NOT as an Authorization: Bearer header. Keep the body bash-3.2
# compatible (macOS ships bash 3.2).
set -u

WS=""
METHOD=""
AS_BOT=0
PARAMS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --workspace) WS="${2:?slack_api: --workspace needs a value}"; shift 2 ;;
    --as-bot)    AS_BOT=1; shift ;;
    -d|--data)   PARAMS+=("${2:?slack_api: -d needs key=value}"); shift 2 ;;
    -h|--help)   sed -n '2,41p' "$0"; exit 0 ;;
    -*)          echo "slack_api: unknown flag $1" >&2; exit 2 ;;
    *)           if [ -n "$METHOD" ]; then echo "slack_api: unexpected arg $1" >&2; exit 2; fi
                 METHOD="$1"; shift ;;
  esac
done
if [ -z "$METHOD" ]; then
  echo "usage: slack_api.sh <method> [--workspace <ws>] [--as-bot] [-d key=value]...   (-h for details)" >&2
  exit 2
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "slack_api: needs jq (see ../SETUP.md). For posting and editing use scripts/post_message.py, which needs only python3." >&2
  exit 2
fi

# Resolve the workspace: flag, then the environment, then the repo's task-flow.json
# (walking up from the working directory, the same lookup post_message.py does).
if [ -z "$WS" ]; then WS="${SLACK_WORKSPACE:-}"; fi
if [ -z "$WS" ]; then
  DIR="$PWD"
  while [ -n "$DIR" ]; do
    if [ -f "$DIR/.claude/task-flow.json" ]; then
      WS=$(jq -r '.slack.workspace // empty' "$DIR/.claude/task-flow.json" 2>/dev/null)
      break
    fi
    [ "$DIR" = "/" ] && break
    DIR=$(dirname "$DIR")
  done
fi
if [ -z "$WS" ]; then
  echo "slack_api: no workspace. Pass --workspace <name>.slack.com, set \$SLACK_WORKSPACE, or add {\"slack\": {\"workspace\": \"...\"}} to .claude/task-flow.json." >&2
  exit 2
fi

# Normalize the selector: strip scheme/path, append .slack.com to a bare slug.
WS="${WS#https://}"; WS="${WS#http://}"; WS="${WS%%/*}"
case "$WS" in *.*) ;; *) WS="$WS.slack.com" ;; esac

if [ "$AS_BOT" = "1" ]; then
  if [ -z "${SLACK_BOT_TOKEN:-}" ]; then
    echo "slack_api: --as-bot needs \$SLACK_BOT_TOKEN" >&2
    exit 2
  fi
  curl_args=( -sS -X POST "https://$WS/api/$METHOD" -H "Authorization: Bearer $SLACK_BOT_TOKEN" )
else
  XOXC=""; XOXD=""
  if command -v security >/dev/null 2>&1; then
    XOXC=$(security find-generic-password -s agent-slack -a "xoxc:https://$WS" -w 2>/dev/null)
    XOXD=$(security find-generic-password -s agent-slack -a xoxd -w 2>/dev/null)
  fi
  # Off macOS there is no Keychain: agent-slack keeps the same session in a JSON store.
  # Keychain still wins where it exists, so this only turns a hard exit into a working call.
  if [ -z "${XOXC:-}" ] || [ -z "${XOXD:-}" ]; then
    for CRED in "${XDG_CONFIG_HOME:-$HOME/.config}/agent-slack/credentials.json" \
                "${APPDATA:-}/agent-slack/credentials.json"; do
      [ -f "$CRED" ] || continue
      XOXC=$(jq -r --arg ws "$WS" '.workspaces[] | select(.workspace_url | contains($ws)) | .auth.xoxc_token // empty' "$CRED" 2>/dev/null | head -1)
      XOXD=$(jq -r --arg ws "$WS" '.workspaces[] | select(.workspace_url | contains($ws)) | .auth.xoxd_cookie // empty' "$CRED" 2>/dev/null | head -1)
      if [ -n "${XOXC:-}" ] && [ -n "${XOXD:-}" ]; then break; fi
    done
  fi
  if [ -z "${XOXC:-}" ] || [ -z "${XOXD:-}" ]; then
    # No session anywhere. Where there is no Keychain and no agent-slack at all
    # (a container), a bot token in the environment is the only credential there
    # is, so use it rather than refuse: the call is then made as the bot, not as
    # the person, which is what the caller gets there.
    if [ -n "${SLACK_BOT_TOKEN:-}" ]; then
      curl_args=( -sS -X POST "https://$WS/api/$METHOD" -H "Authorization: Bearer $SLACK_BOT_TOKEN" )
    else
      echo "slack_api: no agent-slack session for $WS (checked the macOS Keychain and credentials.json) and no \$SLACK_BOT_TOKEN — run the import in ../SETUP.md or set the token" >&2
      exit 2
    fi
  else
    XOXD_ENC=$(printf %s "$XOXD" | jq -sRr @uri)
    curl_args=( -sS -X POST "https://$WS/api/$METHOD" -H "Cookie: d=$XOXD_ENC" --data-urlencode "token=$XOXC" )
  fi
fi
for p in ${PARAMS[@]+"${PARAMS[@]}"}; do
  curl_args+=( --data-urlencode "$p" )
done

RESP=$(curl "${curl_args[@]}") || exit $?
printf '%s\n' "$RESP"
if ! printf '%s' "$RESP" | jq -e '.ok == true' >/dev/null 2>&1; then
  echo "slack_api: $METHOD → ok:false ($(printf '%s' "$RESP" | jq -r '.error // "unparseable response"' 2>/dev/null))" >&2
  exit 1
fi
