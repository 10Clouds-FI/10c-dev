---
name: cleanup
description: "The closing reflection after a change lands: work out what the change just made pointless — superseded implementations, orphaned helpers, features whose reason to exist disappeared — remove the obvious ones and propose the rest. Runs automatically at the end of any non-trivial coding task, and on request: \"what can we delete now\", \"tidy up after this\", \"what is redundant now\", \"remove the old one\", \"posprzątaj\", \"co jest teraz zbędne\", \"usuń stare\"."
metadata:
  version: 1.0.0
  title_en: What did this change make pointless?
  summary_en: The deliberate post-change pass that removes your own orphans and proposes the code your change obsoleted.
  category: [development]
---

# What did this change make pointless?

Adding is easy and an agent will do it forever. The failure mode is the swamp:
a new feature lands, two old ones quietly lose their reason to exist, nobody
removes them, and from then on everyone — human and agent — pays to maintain,
read around and reason about code that should not be there.

This is a **separate, deliberate phase**, run *after* the work is otherwise
done. It is not permission to tidy while building: during implementation you
stay surgical and touch only what's in your way. Here you stop, zoom out, and
look at what your own change has orphaned.

---

## Procedure

### 1. Look at what you actually changed

`git diff` (and `git status`) for the whole task, not just the last edit. Read
it as a stranger would.

### 2. Sort findings into three buckets

**Bucket A — your own mess. Delete it, don't ask.**
Imports, variables, helpers, branches, fixtures, feature flags that *your*
change made unreachable or unused. Removing these is part of finishing the job.

**Bucket B — pre-existing code your change made pointless. Propose it.**
The interesting bucket. Look for:

- an older implementation of the same thing, now superseded
- a workaround that existed only because the thing you just built didn't
- a config option / flag / branch that now has only one possible value
- a feature whose *purpose* was absorbed by the new one
- duplicated logic where yours is strictly better
- tests asserting behaviour that no longer exists

For each, verify before claiming: grep for references across the repo
(including tests, configs, docs, scripts, CI), and check the project model if
one exists. Then present:

| What | Why it's now pointless | Evidence | Recommend |
|---|---|---|---|
| `src/oldSplitter.ts` | superseded by the new settle algorithm | no imports outside its own test | delete |
| `USE_LEGACY_SPLIT` flag | only one branch reachable now | grep: 2 hits, both in the flag's own definition | delete + inline |

Then ask. One message, one decision.

**Bucket C — unrelated rot you happened to notice.**
Mention in a sentence. Do not touch, do not expand the diff, do not turn the
task into a cleanup crusade. If the project model exists, this is worth
recording there as known dead weight so it isn't lost.

### 3. Obvious versus uncertain

- **Obvious → just do it.** A helper only your deleted code called; a test for
  a function that no longer exists; an import nobody uses. No ceremony.
- **Uncertain → propose, with evidence.** Anything reachable from outside,
  anything the model marks `core` or `supporting`, anything you can't prove is
  unreferenced, anything that touches persisted data or a public interface.
- **Never delete on a hunch.** "Looks unused" is not evidence; a grep is.
- Dynamic references are the trap: reflection, string-keyed dispatch, template
  names, DB values, CLI arg names, env-var-driven behaviour. Grep for the
  *string*, not just the symbol.

### 4. Keep the removal separate

Cleanup goes in its own commit, in English, saying what was removed and why it
is safe (`Remove legacy splitter superseded by settle algorithm`). Don't bury a
deletion inside a feature commit — it makes the feature impossible to review
and the deletion impossible to revert on its own.

### 5. Update the project model

If a model exists, this is the moment to change it: retire the entries you
removed, downgrade statuses, and record anything from bucket C as known dead
weight.

---

## What this phase is not

- Not a refactor. Restructuring code that still earns its place is a separate
  task with its own interview.
- Not a style pass. Formatting, naming and import order are not in scope.
- Not an excuse to delete things that predate you and merely look untidy.
  Pointless *because of your change* is the test.
