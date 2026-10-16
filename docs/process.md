# The process this plugin encodes

For a team lead deciding whether to adopt it. This is a description of the working method, not
of the code. It follows the twelve stages of the 10Clouds FI note "How we build with AI agents".
It assumes a team where people run Claude Code sessions against a shared repository, and where
every change that reaches `main` is tracked in a ticket.

## The problem it is aimed at

Agentic coding fails in a small number of repeatable ways:

- The agent guesses at intent instead of asking, and builds the wrong thing quickly.
- It builds a cathedral when a shed was asked for — a database, an auth layer and a config
  system for a thing that needed twenty lines.
- It writes tests for the code it just wrote, so the tests confirm what was built, not what was
  asked for.
- It declares work finished because the code compiles, without anyone driving the actual app.
- It reviews nothing, because reading your own diff feels like reviewing it.
- It leaves behind superseded code nobody dares delete.
- On a shared machine, several sessions edit the same files, restart the same stack, and push
  each other's half-finished commits.

Every element below exists to close one of those. Across all of them the developer decides at
every gate and keeps the responsibility for the code, as without AI.

## 1. Ticket

Every change that reaches `main` has a ticket, a documentation fix included. When work starts
somewhere else, such as a Slack thread or a client message, the agent first drafts the ticket
(summary, description, candidate "done when" conditions), the developer agrees it, and the
ticket is created before any code is written.

The ticket status follows the code:

| Where the code is | Status |
|---|---|
| Local, on the developer's machine | **In Progress** |
| On staging, after a green CI | **In Review** |
| Promoted to production and checked there **by a human** | **Done** |

The agent moves a ticket to In Progress and In Review itself, and never to Done at the end of a
local session. This holds in PR mode too: an open pull request is not In Review, running on
staging is. A synthetic `LOCAL-<date>-<time>` key, or `tracker: "none"`, is allowed only for
local R0/R1 work, and cannot be pushed to `main`.

## 2. Project model

Before working on a codebase, the agent reads the project model: a short map of what each part
of the product is *for*, and its status — core, supporting, nice-to-have, legacy kept for one
reason, or already dead. It is built by reading the code *and* interviewing the people, because
line count does not tell you what matters. It makes the weight of a change come from the product
rather than from the diff size: a change near a core capability gets the interview, the tests
and the critic; a change to something marked dead starts with the question whether it should
exist at all.

## 3. Rung

Before any code, the agent states in one sentence how finished the work is meant to be. The
developer can override it, and going up needs the developer's agreement:

| Rung | What it is | Tests | Reaches `main` |
|---|---|---|---|
| **R0 Probe** | "Can this even work?" The output is an answer, throwaway code | none | no |
| **R1 PoC** | The thinnest end-to-end demonstration, happy path only | optional, from the test-design agent | no |
| **R2 MVP** | Usable for its purpose | unit and e2e on the main paths | yes |
| **R3 Hardened** | Edge cases, error handling, documentation | R2, plus edge cases and failure modes | yes |

The ceremony scales with the rung, so a one-line fix does not carry the weight of a new
feature. A one-line fix that ships is R2 with a small ceremony, not R0. The ratchet is one-way:
the agent may discover mid-task that the work is heavier than assumed, say so, and step up with
agreement; it never quietly steps down.

## 4. Interview and Spec

The agent interviews the developer, **one question per message, never a list**, until the goal
can be stated without hedging. Left alone, a model fills gaps with assumptions. The ticket is
input to the interview and does not replace it. The highest-value question is which door the
person who will use this comes through, and what state they are in when they arrive.

The interview ends with a short **Spec** in the conversation, never as a file in the repo: the
goal, what is out of scope, a plan with a check per step, and two to four "done when" conditions
written as what a user would observe through the door they will actually use. The finished work
is checked against these conditions at the end, by the agent and by the critic.

## 5. Tests first

Unit and end-to-end tests are derived from the "done when" conditions by the **test-design
agent**, an agent separate from the one that writes the code, **before the implementation
exists**. An agent that writes tests for its own code tends to test what it built; designing
them first, with a separate agent, removes that bias. At R2 and R3 this is mandatory, and every
condition that describes a user flow gets an end-to-end test. At R1 it is optional. A bug fix
starts with a test that reproduces the bug. The coding agent may not weaken those tests without
telling the developer.

## 6. Build

Each area of the repository has its own rule file. The agent reads the rules for every file it
is about to touch before the first edit, and a rule that looks wrong is raised with the
developer. It builds the smallest change that meets the spec, with no edits to neighbouring code
and no abstractions for a single use, and shows the changes step by step. The developer accepts
the plan once; Claude Code's own edit prompts cover each step after that.

## 7. Verify on the running app

Passing checks do not show that the feature works for a user. The agent verifies **every** change
on what a user touches: it drives the UI in a browser, calls the API, reads the worker logs and
checks the data the change was supposed to create. A failure goes back to the build step. When
the browser tooling is unavailable the agent says so and hands back a manual checklist;
fabricated browser results are worse than none. It ends with a table of each "done when"
condition, how it was observed, and whether it holds.

## 8. Code review

A **code-review agent** reads the diff in a fresh context, without the build conversation, and
reports findings from blocker to nit, together with the results of the project's lint, type and
test checks and a check for breaking changes. The building agent fixes blockers and majors
before the commit and shows the developer what it fixed; the developer can also look at the
findings first. Minors and nits are fixed in files the change already touches, or recorded as a
comment on the ticket for later. The review summary goes into the commit message.

## 9. Cleanup

When the change works, a cleanup pass asks what the change made pointless. The agent deletes its
own leftovers, proposes removal of older code that lost its purpose with evidence from the
codebase, and updates the project model. Accepted removals go in a separate commit.

## 10. Critic

The **critic agent** starts from an empty context and receives only the ticket, its "done when"
conditions and the running application. Cleanup has already run, so its PASS covers the final diff. It never sees the code or how the task was solved. It
builds a plan of at least five scenarios (the main path, the original bug, edge cases,
concurrent actions, regressions), drives the app end to end in a browser trying to break it, and
returns PASS or FAIL. A FAIL goes back to the build step; after the fix the critic reruns on the
failed scenarios, for at most two rounds before the developer is brought in. A partial pass is a
FAIL.

The critic is **mandatory for risky changes** (see stage 11) and for changes near a core
capability. For anything else the developer decides whether to run it.

## 11. Commit and push

The agent proposes the commit with a ready message and waits for the developer's yes. It stages
only the files of the task, never rewrites history, and commits under the developer's own name.
It offers two ways out: a push to `main` (the default, set by `git.mode`), or a pull request when
a change needs a second pair of eyes. Only R2 and R3 work is offered either.

Developers often run several sessions on one machine. The **shared board** records, for each
live session, its ticket, the files it touches and whether it is using the local stack. Hooks
warn **before** a session edits a file a neighbour is editing, restarts a stack a neighbour is
testing against, or pushes commits that belong to another session. They run automatically, so a
session cannot skip them. A hotspot (an expensive-to-collide path) raises a blocker.

Changes to tenant isolation, authorization, migrations, pipelines or a chat gateway count as
**risky**; the list is configured per repository in `risky`, with these as the defaults. For a
risky change the critic is mandatory, and the push waits until a heads-up has been posted in the
project channel saying what goes in and whom it may affect (the agent drafts it and posts it as
the developer on a yes). A change that breaks a contract, such as a removed API field or a renamed
column, needs the approval of the area owner first, from the `owners` map or CODEOWNERS.

## 12. Staging and production

A push to `main` starts the CI/CD pipeline: unit tests run first, and only a green build is
deployed to staging. The agent follows the run, and moves the ticket to **In Review** only once
the code is on staging; on a red run the ticket stays In Progress. Before a release reaches
production, end-to-end tests drive the full stack through Playwright. The plugin does not ship
CI templates; setup checks that the repository has a unit gate and an e2e gate and reports it if
either is missing.

Then a human checks the change on production, with `/10c-dev:release-check <KEY>`, from the
testing brief in the ticket. If it holds, the developer confirms and the ticket becomes **Done**.
If the check finds a bug, a new ticket is drafted and created for it, and the original ticket
stays In Review until the next check.

## What a team has to supply

One file in the repository, `.claude/task-flow.json`: the tracker and project key, the git base
branch and the default push mode, the commands that verify a change (globally, per area and
end-to-end), how to start the app and where it serves, which rule files apply to which paths,
the risky areas and their owners, how to read the CI runs and the staging and production URLs,
the hotspots, the stack commands, and the language for ticket comments. Everything else in the
workflow is project-independent.

Credentials never go in that file. They live in the environment or in per-user storage outside
the repository.
