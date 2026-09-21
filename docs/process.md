# The process this plugin encodes

For a team lead deciding whether to adopt it. This is a description of the working method, not
of the code. It assumes a team where people run Claude Code sessions against a shared
repository, and where work is tracked somewhere (Jira, or nowhere at all).

## The problem it is aimed at

Agentic coding fails in a small number of repeatable ways:

- The agent guesses at intent instead of asking, and builds the wrong thing quickly.
- It builds a cathedral when a shed was asked for — a database, an auth layer and a config
  system for a thing that needed twenty lines.
- It declares work finished because the code compiles, without anyone driving the actual app.
- It reviews nothing, because reading your own diff feels like reviewing it.
- It leaves behind superseded code nobody dares delete.
- On a shared machine, several sessions edit the same files, restart the same stack, and push
  each other's half-finished commits.

Every element below exists to close one of those.

## The rung ladder

Before any code, the session states out loud how finished the work is meant to be, in one
sentence the human can override:

| Rung | What it is | Tests | New dependencies |
|---|---|---|---|
| **R0 Probe** | "Can this even work?" The output is an answer, not code you keep | none | throwaway, labelled |
| **R1 PoC** | The thinnest end-to-end demonstration, happy path only | none | none unless unavoidable |
| **R2 MVP** | Actually usable for its purpose | core paths covered | only what the feature needs |
| **R3 Hardened** | Edge cases, failure modes, polish, docs | unit and e2e where meaningful | as needed |

Two rules make this work. **Default to the lowest rung that answers the request** — most
requests are R1. And **the ratchet is one-way**: the session may discover mid-task that the
work is heavier than assumed, say so, and step up with agreement; it never quietly steps down,
and never climbs on its own initiative.

The practical effect is that "build me a thing that splits expenses" produces a working page in
an afternoon rather than a schema, a migration and a login screen.

## The interview

Before designing, the session asks questions — **one per message, never a list**. A numbered
wall of questions is a form, and nobody fills in a form. Because they come one at a time, each
answer changes the next question, which is the whole point.

Questions are concrete and answerable ("web, mobile, or a bot?", not "what are your
requirements?"). Where the answers are enumerable, they are offered, so answering costs one
word. The interview continues until the goal can be stated without hedging — usually a handful
of questions, often one at R0.

The highest-value question, and the one nobody volunteers the answer to: **which door does the
person who will use this come through, and what state are they in when they arrive?** A link
you send them, a tab they are already logged into, a file you hand over. Its absence is
invisible until someone tries the thing and it does not work for them.

After the questions, the session pushes back: what could go wrong, how this is normally done, a
cheaper path, a real tradeoff. Up to five short notes, only where genuinely relevant.

## The tiny spec

Before the first edit, a short spec goes **in the conversation, never as a file in the repo**:
goal in one sentence, two to four "done when" conditions, what is explicitly out of scope, the
plan with a verification step per step, and the rung.

The "done when" conditions are written as **what a human would observe, through the door they
will actually use** — "a client opens the link in a browser where they are not logged in, signs
in, and lands on the page", not "the endpoint refuses an unauthenticated request". The second
is a fact about the code; the first is the thing that was asked for. Criteria written around
what is convenient to measure look like success the whole time you are working.

## Build, verify, review

- **Build the smallest thing**, surgically, surfacing changes incrementally rather than
  batching ten files before the first check-in. Before touching an area, the session loads the
  repo's own rules for that area (configured per path prefix), and they are mandatory, not
  advisory.
- **Tests from R2 up**, at the level of the problem a module solves. A bug gets a reproducing
  test first.
- **Prove it on the artifact a human uses.** For UI work that means driving the running app in
  a real browser; for a backend change it means an actual call, an actual worker log. Compiling
  is not the feature working, and fabricated browser results are worse than none — when the
  browser tooling is unavailable, the session says so and hands back a manual checklist.
- **Self code-review from R2 up**: the session runs a structured review over its own complete
  diff, fixes everything at blocker and major severity, and lists the minor findings for the
  human instead of silently widening the scope. A finding about pre-existing code goes on the
  cleanup list, not into a drive-by fix.

## The adversarial critic

Optional, offered once at the end, and worth most on backend, authorization and
security-sensitive work — less on a visual tweak.

The critic runs in its own context as a **black-box** tester. It never reads the source and
never edits anything. It fetches the ticket itself, builds an attack plan of at least five
distinct scenarios (happy path, the exact original bug, edge cases, rapid or concurrent
actions, regression spots), drives the live app trying to break it, and returns PASS or FAIL
with exact observed state. A partial pass is a FAIL.

Run it **once**, at the end. Looping it produces endless nitpicks.

## Cleanup and the project model

After the work lands and before anything is committed, a closing reflection asks what this
change just made pointless. The session deletes its own orphans, proposes — with evidence — the
pre-existing code the change made redundant, and leaves unrelated rot alone with a one-line
mention. An accepted removal lands in its own commit, never inside the feature commit.

Separately, the team keeps a short **project model**: a map of what each part of the codebase
is *for*, and its status — load-bearing, nice-to-have, legacy kept alive for one specific
reason, or already dead. It is built by reading the code *and* interviewing the people, because
line count does not tell you what matters. Its job is to make the weight of a change come from
the product rather than from the diff size: a change near a load-bearing capability earns the
interview, the tests and the critic; a change to something marked dead earns the question
"should this exist at all" before any code is written.

## Ticket status follows the code

The single rule that keeps a board honest:

| Where the code is | Status |
|---|---|
| Local, on a branch or uncommitted | **In Progress** |
| Pushed to the base branch, or in an open PR — so it is where reviewers and staging can see it | **In Review** |
| Promoted to production and checked there **by a human** | **Done** |

The status says where the code *is*, never how the conversation went. No step in this workflow
moves a ticket ahead of that — in particular, nothing marks a ticket Done at the end of a local
session. If a workflow transition cannot be found, the session reports the available ones and
asks rather than guessing.

## Commit and push

The session **offers** to commit and push once the code works, the diff is reviewed and cleanup
is done — one question, with the proposed commit message in it. It does not wait to be asked,
and it does not act unasked. It stages the files of that task only, never everything. It never
rewrites history: no stash, reset, rebase, merge or force-push — when the tree or the remote is
not what was expected, it describes what it sees and stops.

## The session board

Several Claude Code sessions on one machine, often in one checkout, is the normal case, and it
is where the expensive accidents happen. Hooks maintain a small shared board so that every
session can see, and is told about:

- which ticket each live session owns, its phase, its branch, and which files it is touching
- **file overlap** — a file this task touches that a neighbour is also editing is reported to
  the developer, by neighbour name, *before the first edit*, with three options: continue,
  message that session, or wait
- **hotspots** — configured paths where a collision is especially expensive
- **blockers** — a session verifying against the local stack holds it, and neighbours are asked
  before they restart or destroy it
- **pushes** — before a push, the board names any neighbour sharing the checkout and lists the
  commits the push would carry along. One pusher at a time, negotiated between the sessions.

None of this is advisory decoration: the checks run as hooks, so a session cannot route around
them by not looking.

## What a team has to supply

One file in the repository, `.claude/task-flow.json`: the tracker and project key, the git base
branch and whether the team uses PRs, the commands that verify a change (globally and per
area), how to start the app and where it serves, which rule files apply to which paths, the
hotspots, the stack commands, and the language for ticket comments. Everything else in the
workflow is project-independent.

Credentials never go in that file. They live in the environment or in per-user storage outside
the repository.
