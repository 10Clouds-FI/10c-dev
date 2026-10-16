---
name: release-check
description: "The production check and the Done stage. Run with a ticket key after a release: walks the developer through checking the change on production from the ticket's testing brief, then moves the ticket to Done on their yes, or, when they find a bug, drafts a new linked ticket and leaves this one In Review. Use for \"check it on production\", \"release check ABC-123\", \"is this live and working\", \"mark ABC-123 done\"."
metadata:
  version: 1.0.0
  title_en: Production check
  summary_en: A human checks the released change on production; Done on a yes, a new ticket on a bug.
  category: [development]
allowed-tools: Bash, Read, Grep, Glob, mcp__atlassian__*
---

# Production check

The last stage of the cycle. A human checks the released change on production, and only then
does the ticket become Done. The `implement` skill never sets Done; this skill does, on the
developer's confirmation.

Read `.claude/task-flow.json` first: `ci.production.url`, `ci.e2e`, `statusMap`, `transitionIds`,
`reporting`. Ticket access is the same as in `implement`: the `atlassian` MCP server, else the
`jira` skill scripts.

## Usage

`release-check <KEY>` after a release. A `LOCAL-` key or `tracker: "none"` has nothing to
check here: say so and stop.

## Steps

1. **Fetch the ticket** (summary, status, comments). If it is not In Review, say what its status
   is and ask whether to continue; Done is never set for a ticket the code has not reached
   staging for.
2. **Find the testing brief**: the In Review comment `implement` left (scenario, expected
   outcomes, regression watch-list), and the ticket's "done when" conditions. If there is no
   brief, build one from the conditions and say so.
3. **Confirm it is released.** If `ci.e2e` is configured, check that the e2e gate passed for
   the release (`ci.e2e.watch`, or `gh run list`). Red or missing: report it and stop, the code
   has not been cleared for production.
4. **Walk the developer through it.** Give the production URL (`ci.production.url`) and the
   brief's steps one at a time, with the expected outcome of each, then the regression
   watch-list. The developer does the clicking; do not drive production yourself and do not
   run anything destructive there.
5. **Ask once:** "Does it work on production?"
   - **Yes:** transition to **Done** (`transitionIds.done` / `statusMap.done`) and comment
     "Checked on production by <developer>" in `reporting.language`. This is the only place a
     ticket gets Done.
   - **A bug:** do not transition. The original ticket stays In Review until the next check.
     Draft a new ticket as in `implement` Step 0: summary, description (what was seen, where,
     steps to reproduce, link to the original), candidate "done when" conditions. Show it,
     create it on a yes (`mcp__atlassian__createJiraIssue` or
     `${CLAUDE_PLUGIN_ROOT}/skills/jira/scripts/create_issue.py`), link it to the original, and
     add a comment on the original naming the new key. Offer to start `implement` on it.
   - **Not checked yet:** leave everything as is.

## Don'ts

- Don't set Done without the developer's explicit yes, and not on the strength of green CI.
- Don't mark the original Done when a bug was found, even a small one.
- Don't create the bug ticket unasked.
- Don't test on production yourself beyond reading; the human checks.
