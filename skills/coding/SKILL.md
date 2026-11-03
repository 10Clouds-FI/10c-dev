---
name: coding
description: "Use for ANY request to write, change, prototype, refactor or debug code — a new app, a new feature, a bug fix, a spike, \"try something\", \"add a feature\", \"fix this\", \"let's try\", \"build me an app\", \"refactor this\", \"dodaj funkcję\", \"popraw\", \"spróbujmy\", \"zrób aplikację\", \"zrefaktoruj\". Interviews the human before building, picks the right rung of the prototype→production ladder, builds the minimum that works, then reflects on what the change made obsolete. Do NOT skip it because the task looks small."
metadata:
  version: 1.0.0
  title_en: Coding without losing your mind
  summary_en: The rung ladder, the one-question interview, a tiny spec, the smallest build, and proof on the real artifact.
  category: [development]
---

# Coding without losing your mind

Most of the pain of agentic coding comes from five moves: guessing instead of
asking, building a cathedral when a shed was asked for, climbing straight to
production when the human wanted to poke at an idea, declaring the work done
without anyone reviewing it, and leaving behind a pile of code nobody dares
delete. This skill exists to stop all five.

**Run the phases in order:** rung, interview, spec, tests first, code, proof,
review. Ceremony scales with the rung and with the size of the diff (§1):
a value change or a small diff gets no separate test or review agent.

---

## 1. Say the rung out loud

Before anything else, classify the work and state the classification in one
sentence, so the human can override it:

| Rung | What it is | Output | Tests | Deps / infra |
|---|---|---|---|---|
| **R0 Probe** | "Can this even work?", "does this API return what we need?" | An **answer**, not code you keep | none | throwaway, label it |
| **R1 PoC** | Thinnest thing that shows the idea working end to end, happy path only | Running code, ugly is fine | optional (test-design agent) | none new unless unavoidable |
| **R2 MVP** | Something actually usable for its purpose | Working feature | unit + e2e, main paths | only what the feature needs |
| **R3 Hardened** | Edge cases, failures, polish, docs | Production-shaped | unit + e2e, edge cases and failures too | as needed |

Rules:

- **Default to the lowest rung that answers the request.** "Build an app that
  splits trip expenses" is R1, not R3.
- **Only R2 and R3 go to `main`.** R0 and R1 output stays local or throwaway.
  If it is going to ship, step up to R2 first, with the developer's agreement.
  A one-line fix that ships is R2 with a small ceremony (a reproducing test, a
  short spec), not R0.
- **The ratchet is one-way.** You may discover mid-task that the work is
  heavier than you thought — stop, say so, get agreement, step up. You never
  quietly step *down*, and you never climb *up* on your own initiative.
- **Never build a rung nobody asked for.** No database because "we'll need it
  later". No auth because "real apps have auth". No design system because the
  page looked plain. Those are R2/R3 concerns; at R1 they are noise.
- Each rung ends at a checkpoint: show what works, say what the next rung
  would add, and let the human decide whether to climb.

Explicit spec + explicit "just build it" → go straight to the rung the spec
describes and stop asking for permission at every step.

### Size the checks to the change

The rung says how far the work goes; the **size** of the change says how much
checking it needs. Name the size together with the rung ("R2, a value
change"), and again before the tests (§4) and the review (§7), measured on the
real diff (`git diff --stat`, comment-only lines not counted). Three sizes:

| Size | What the diff is | Tests (§4) | Review (§7) | Cleanup (§8) |
|---|---|---|---|---|
| **Value change** | Only literal values change in existing code or config — a number, a timeout, a threshold, a limit, a size, a flag's value — plus comments. No line of code added or removed; no name, condition, operator, signature or string key changes. | No test-design agent. Run the existing tests and checks that cover the touched files. A test that pins the old value gets that one value changed. | None. | None. |
| **Small** | All of: at most ~30 changed lines of code (added + removed, comments excluded), no new or deleted file, no changed public interface or format (exported API, route, event, CLI flag, schema, config or file format another program reads), no risky area (auth, permissions, data scoping, money, migrations, concurrency, the repo's own `risky` list). | No test-design agent. You write the test that pins the changed behaviour yourself (for a bug, the reproducing test first). Run only the tests covering the touched paths. | No separate agent: a self-review in your own context against the short list below. | One line: did this make anything pointless? |
| **Large** | Anything else: more lines, new files or modules, new logic beyond a local edit, a changed interface or format, a risky area, a port or migration of a whole component. | Test-design agent at R2+ (§4). | Independent `code-review-agent` (§7), its gate scoped to the touched paths. | The `cleanup` skill. |

Why ~30 lines: that is one screen. A diff that size fits whole in your own
context, so a fresh reviewer adds little beyond the checklist below, while
spawning one costs minutes and the whole suite costs more; past one screen,
your blind spots start to matter more than the minutes. A value change is
checked by running it, not by reading it: the only question is whether the new
value does what was asked, and only the running artifact answers that (§6).

**Self-review list (Small):** re-read the whole diff once, then check each:
1. it does what the spec's "done when" asks, and nothing on the out-of-scope list;
2. every caller of a changed function or value still gets what it expects;
3. no new failure path is left unhandled where the surrounding code handles it;
4. no secret, debug output or leftover experiment in the diff;
5. the tests covering the touched paths ran and passed (name the command).
Post the five lines with ✓/✗ in chat. Any ✗ is fixed before §6.

Rules:

- **The size is a fact about the diff, not a feeling.** Count it. A change
  that grows past its size mid-task moves up, and you say so; it never moves
  down because the deadline is close.
- **Do not rework tests or check scripts inside a value change or a small
  change.** If a check expects the old value, change that value. If the check
  itself is wrong, say so and leave it for a task of its own.
- §6 (prove it on the artifact) applies to every size. Ceremony shrinks;
  looking at the real result never does.

---

## 2. Interview before you build

Read `references/interview.md` for the question bank. Rules of engagement:

- **Ask before designing, not after implementing.** This is the single
  highest-value phase; do not skip it because the request sounds clear.
- **If a person other than you will open the thing, ask which door they come
  through** — a link you send them, a tab inside something they are already
  logged into, a file you hand over — **and what state they are in when they
  arrive.** Nobody volunteers this: to them it is obvious, and it is the piece
  that decides whether what you build works for them at all. It is also the
  question whose absence is invisible until they try it.
- Ask **concrete, answerable** questions — "web, mobile or a Telegram bot?",
  not "what are your requirements?".
- **ONE QUESTION PER MESSAGE. Never a list.** Ask, wait for the answer, react
  to it — a follow-up if the answer opened something up, otherwise the next
  question. A wall of numbered questions is not an interview, it is a form, and
  nobody wants to fill in a form. This rule has no exceptions and no "but this
  batch is short".
- Because you ask one at a time, each answer can change what you ask next.
  That is the point: a real interview is a conversation, not a questionnaire.
- Where the plausible answers are enumerable, offer them (AskUserQuestion, or
  "web / mobile / Telegram bot / something else?") so answering costs one word.
- Keep going until you can state the goal without hedging — usually a handful
  of questions, at R0 often one. Do not start coding with questions outstanding.
- If the answer is "do whatever you think is best" — give your recommendation and get an
  explicit yes to *that*, don't treat it as a blank cheque.

### Then push back and contribute

The human asked for a thing; you also know things. After the questions (or with
them), offer up to ~5 short notes, only where genuinely relevant:

- **What could go wrong** — the failure mode they probably haven't pictured.
- **How this is normally done** — the boring standard approach, if theirs
  diverges from it for no stated reason.
- **A cheaper path** — if 20 lines get 80% of the value, say so.
- **A real tradeoff** — two viable shapes, with the consequence of each.

Label them as suggestions, keep each to a sentence or two, and drop the ones
that are filler. Do not pad. Silence beats noise.

---

## 3. Write yourself a tiny spec

Before the first edit, post in chat (**never as a file in the user's repo**):

```
Goal:        one sentence, in terms of the problem, not the code
Done when:   2–4 conditions, each checkable FROM THE USER'S SIDE
Out of scope: the things you are deliberately NOT doing
Plan:        1. step → verify: how you'll know
             2. step → verify: ...
Rung:        R1
```

Keep it short. It is a leash for you, not a deliverable for them. Track the
steps with TodoWrite for anything beyond two steps.

These "done when" conditions are the contract. They feed the tests (§4), the
end check (§6) and the critic, so write them as user observations, not as facts
about your code.

**Write "done when" as what the human would observe, through the door they
will actually use.** For anything a person opens — a page, a link you hand
over, an app — name the door in the condition itself: *"a client opens the
link in a browser where they are not logged in, signs in, and lands on the
page"*, not *"the endpoint refuses an unauthenticated request"*. The second
one is a fact about your code; the first is the thing that was asked for, and
they are not the same sentence.

Two failure modes this closes, both of which look like success while you work:

- **A criterion written around what you can conveniently measure.** `curl` has
  no login flow, so a 401 from `curl` reads as "the gate works" while a person
  opening that address in a window gets raw JSON and a dead end. If the user's
  door needs a browser, the criterion needs a browser; if you cannot open one,
  say the condition is unverified rather than quietly swapping in the check you
  can run.
- **A door nobody mentioned.** The human pictured sharing a link directly and
  never said so, because to them it was obvious. That is what §2's "how do they
  get to it" question is for — and if the answer never came, the condition you
  write is a guess, so say which door you assumed.

---

## 4. Tests first (R2+, Large changes)

**Mandatory for a Large change at R2 and R3, optional at R1, never at R0.** A
value change or a Small change (§1) gets no test-design agent: run the existing
tests covering the touched paths, and for a Small change that alters behaviour
write the one test that pins it yourself. For a Large change the tests are written
from the spec, by an agent that does not write the code, **before the code
exists**. Spawn the `test-design-agent` (`agents/test-design-agent.md`) with the
ticket (or topic), the rung, the repo path, the "done when" conditions and the out-of-scope list. Give it
no plan, no conversation and no implementation: that is what keeps the tests
honest.

- It writes **failing** unit tests and e2e tests. Every "done when" condition
  that describes a user flow gets an e2e test. For a bug, the first test
  reproduces the bug.
- Run them and confirm they fail for the right reason (missing behaviour, not a
  typo or a broken import). A test that passes before the code exists asserts
  nothing.
- Test at the level of **the problem a module solves**, not at the level of
  trivial functions. "Does the splitter settle debts correctly" yes; "does this
  getter return the field" no.
- Tests are the executable half of the project model (see below): if the model
  says the module exists to solve problem X, there should be a test asserting X.
- **You may not weaken, delete or edit those tests to make them pass.** If one
  is wrong, say so to the developer and change it only with their agreement.
  If the internals change but the problem solved does not, the tests should not
  need to change; if they do, one of the two was wrong, and you say which.

---

## 5. Write the code, the smallest that satisfies the spec

- No feature beyond what was asked. No speculative flexibility, configurability
  or extension points.
- No new dependency unless it is doing real work you would otherwise hand-write
  badly. Say why when you add one.
- No abstraction for a single call site. No error handling for impossible
  states.
- No unrequested UI polish, CSS frameworks, animations, dark mode, or icon
  sets. Plain and working beats pretty and half-broken. Beauty is a separate,
  explicitly requested task.
- Build **top-down from the goal**, not bottom-up from a foundation. Don't lay
  a schema, a service layer and a config system before anything runs.
- If you wrote 200 lines and 50 would do, rewrite it before showing it.
- Match the surrounding code's style even when you'd do it differently.

**Surgical while building.** Don't "improve" adjacent code, reflow comments,
reorder imports or refactor things that are not in your way. Every changed line
should trace to the request or to your own mess. Cleanup is phase 8, and it is
deliberate, not a side effect.

**Show it step by step.** The developer accepted the plan once (§3), and Claude
Code's edit prompts cover each edit, so do not add pauses. After each plan step,
say in a line or two what changed and what that step's check returned, then
carry on. If a check fails or the plan has to change, stop and say so.

**Run the tests from §4 as you go.** The code is done when they pass, not
before. At R2+ they are the target; at R1 run whatever check the plan named.

---

## 6. Prove it on the artifact a human uses

**Before the word "done", at every rung.** A change is verified when you have
looked at the thing the user depends on. Not at what the system says about
itself.

- **A status field is a claim, not evidence.** `last_status = ok`, a green run, a
  200, "the deploy succeeded", "it answered once" — all of these are the system
  reporting on itself, and all of them survive a component that is doing
  nothing. Read the data instead: fresh rows, a moving watermark, a growing
  count, the file on disk, the page in the browser.
- **A suspiciously fast success is a failure.** A job that used to take two
  minutes and now takes six seconds did not get faster.
- **No traffic means no evidence.** "Nobody has used it yet" is zero
  information. Report it as "not verified — there was no traffic", never as
  "working".
- **If you bypassed the normal code path** — restored a database by hand, wrote a
  row instead of calling the endpoint, provisioned something manually — then open
  that code path and list, line by line, every invariant it establishes:
  ownership, grants, secondary roles, settings, indexes, side tables. Check every
  one of them, not only the one that surfaced as an error. The invariants you
  skipped did not break; they were never established, so nothing will report them
  as broken.

**End with a check against the spec.** Walk the "done when" conditions from §3
one by one and post the result:

```
Condition                         How it was observed          Result
a client opens the link, signs in  browser, logged-out window   ✓
the export lists 3 columns         opened the downloaded file   ✗ (2 columns)
rows older than a year are hidden  no such data locally         unverified (no data)
```

Each condition gets ✓, ✗ or "unverified (why)". Any ✗ goes back to §5. An
"unverified" is reported to the developer, never rounded up to ✓.

Cost of skipping this, measured: a hand-migrated database left a schema owned by
the wrong role. Reads worked, so the account looked healthy, while the sync
reported success 118 times and wrote nothing for 29 hours. Found by the client,
not by us. Both fixes took five minutes each; only the looking was missing.

## 7. Review the diff before you call it done (R2+, Large changes)

**Mandatory for a Large change at R2+, on request at R1, never at R0.** A value
change gets no review; a Small change gets the self-review list from §1 in your
own context, not an agent. For a Large change the review is **independent**:
spawn the `code-review-agent` in a fresh context and give it only the diff range (the
current branch against its merge-base, uncommitted changes included), the ticket key and
the spec. Never the build conversation: a reviewer that shares your context shares your
blind spots. It runs the `code-review` skill and returns a validation gate that actually
ran, a severity-ranked list (blocker / major / minor / nit), a breaking-change checklist,
and a mechanical verdict.

- You fix every **blocker** and **major** yourself, then show the developer what you
  fixed. Minors and nits follow the disposition the review gives them (fix now if the
  file is already in the diff, otherwise a comment on the ticket); do not silently expand
  scope.
- The validation gate is scoped to the diff: the fast whole-repo checks from
  `verify.commands` (lint, typecheck, build) plus the tests of the touched paths
  (`verify.byArea`, or the test runner's path filter), not the whole suite. The
  whole suite is for a change to a shared module many paths depend on, and for
  CI. The gate comes from the repo's `.claude/task-flow.json`. If the repo has no such
  file, **do not scaffold config into someone's repo** — that is exactly the
  "plan file in their repo" this skill forbids. Derive the gate from what the
  repo already has (`package.json` scripts, `Makefile`, CI config, `CLAUDE.md`)
  and state which commands you ran. Only write the config when the human asks.
- The review covers **this** diff. A finding about pre-existing code goes into
  phase 8's list, not into a drive-by fix.
- **A second review after the fixes is a new, equally blind one.** Spawn a fresh
  `code-review-agent` with the same brief as the first: the whole diff (merge-base to
  the current head, fixes included), the ticket key, the spec, the gate. Never the
  previous findings, a "this commit claims to fix X" list, a "focus on the fix commits"
  hint, or your explanation of why a test fails. A reviewer told where to look checks
  your list and stops looking. Whether the old findings are fixed is shown by the
  reproducing tests written for them (§4), not by the reviewer.
- **The brief carries no conclusions of yours**, in the first review either: no "known
  failure, it is only X", no "this part is fine". If something is known to fail, say
  that it fails, not why.

---

## 8. Closing reflection — what did this make pointless?

**Mandatory before you call a Large change done at R1+.** Load the `cleanup`
skill and run it. A Small change gets one line instead (did it make anything
pointless?); a value change gets nothing. In short: your change often obsoletes older code — a superseded
implementation, a now-unreachable branch, a feature whose reason to exist just
disappeared. Obvious ones you remove yourself; the rest you list and propose.
Leaving them is how a codebase turns into a swamp nobody can reason about.

---

## 9. The project model

Reasoning about a codebase by reading code makes every 100 lines look equally
important. They are not. Before non-trivial work in an existing repo:

- Check for a project model (the `project-model` skill knows where they live).
- **If one exists, read it first** and use it to weigh decisions: what is
  load-bearing, what is nice-to-have, what is legacy kept alive for one reason,
  what is already dead.
- If none exists and the task is R2+ or touches unfamiliar areas, offer to
  build one — it is a one-time interview, and it pays for itself the first time
  you avoid maintaining something that should have been deleted.
- **After the work lands, update the model**: new capability added, old one
  retired, status changed. A stale model is worse than none.

---

## 10. Written artifacts are in English

Talk to the human in whatever language they use. But **everything that gets
written down and stays** — commit messages, code comments, identifiers, docs,
READMEs, PR descriptions, the project model — is in **English**, always, even
when the whole conversation is in another language. Artifacts outlive the
conversation and are read by people who were not in it.

- **Commit messages:** imperative mood, say what changed and why, no emoji.
- One coherent change per commit; don't bundle unrelated cleanup with a feature.
- Commit when asked to. If the repo's own conventions (CLAUDE.md, contributing
  docs) say otherwise, they win.

---

## Red flags

| Thought | Reality |
|---|---|
| "It's obvious what they want" | It is obvious to you because you picked one reading. Ask. |
| "I'll ask after I show them something" | You'll show them the wrong thing and burn the round trip. |
| "This is too small to interview" | Then it's one question, not zero. |
| "They didn't say who opens it, so it's me" | The most expensive assumption in this file. Ask which door, and in what state the person arrives. |
| "It returns the right status code, so it works" | A status code is not a door. Try the thing the way the human will. |
| "While I'm here I'll also…" | You are not here for that. Note it, move on. |
| "They'll want this configurable later" | They'll ask later. Later is cheaper than wrong now. |
| "It needs a proper architecture" | At R1 it needs to run. |
| "Tests would slow down this prototype" | Correct — that's why R0 has none. Don't use it as an excuse at R2. |
| "I'll write the tests after, I know what the code does" | Tests written from the code assert the code. At R2+ they come first, from the spec, from another agent. |
| "It's a one-liner, call it R0 and push" | R0 and R1 never reach `main`. A shippable fix is R2 with a small ceremony. |
| "The old code still works, leave it" | It works and it is now pointless. That is exactly what phase 8 is for. |
| "The job says ok, so it works" | It says it ran. Read the data it was supposed to write. |
| "I fixed the error it showed me" | You fixed the one that surfaced. List the rest from the code. |
| "Nobody has complained, so it's fine" | Nobody has used it. That is not the same sentence. |
| "I read my diff, it's fine" | For a Large change, reading is not reviewing: phase 7 runs the gate and ranks findings. For a Small one, run the §1 list and the touched tests. |
| "It's one value, but let me get it reviewed to be safe" | A value change is checked by running it. A reviewer reading `timeout = 30` → `timeout = 60` learns nothing that running it doesn't. |
| "The check fails on the new value, I'll rework the check" | Change the one value it expects. Reworking checks is a task of its own. |
| "I'll write a plan file in their repo" | Their repo is not your notebook. Chat, or the project model directory. |
