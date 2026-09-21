---
name: project-model
description: "Build and maintain a high-level map of what a project is FOR — which problem each part solves, what is load-bearing, what is nice-to-have, what is legacy kept alive for one reason, what is already dead. Use when starting work on an unfamiliar repo, when asked to \"explore this codebase\", \"map this project\", \"what does this project even do\", \"poznaj projekt\", \"zbuduj mapę projektu\", and to update the map after a feature lands or a capability is retired. Built by reading the code AND interviewing the human — not by reading the code alone."
metadata:
  version: 1.0.0
  title_en: The project model
  summary_en: A per-capability map of what the project is for, how load-bearing each part is, and what is already dead.
  category: [development]
---

# The project model

A code map tells you what exists. It cannot tell you what matters. Read code
alone and every hundred lines look equally important — the hundred lines that
are the whole point of the product and the hundred lines someone vibe-coded one
evening for fun look identical, and the big ones look most important of all.
That mistake is what makes an agent defend dead code, maintain a feature nobody
uses, and refuse to delete the thing that should obviously go.

The project model fixes that by recording, per capability: **which problem it
solves, for whom, and how load-bearing it is.** It is written in the language of
the product, not of the code.

Only a human knows some of this. So this skill **interviews**.

---

## Where the model lives

```
docs/PROJECT_MODEL.md
```

One model for this repository, committed and shared like the rest of `docs/`.
It is team knowledge, so it is updated in the same session that changes the
project (see "Keeping it current") and it goes through the same PR as the
change that made it stale. Add `docs/PROJECT_MODEL_OPEN_QUESTIONS.md` only if
there is a real backlog of unknowns.

---

## Building a model

### 1. Recon quietly first (don't ask what you can read)

Skim, don't deep-read: README, package manifest / pyproject / go.mod, entry
points, route or command tables, top-level directory names, `git log --stat`
for the last few months to see what actually changes, test directories to see
what someone cared enough to protect.

Produce a **draft hypothesis**: a list of candidate capabilities with a guess at
what each is for. Guessing here is fine — the interview corrects you, and a
wrong guess is easier for a human to correct than an open question.

### 2. Interview, one question at a time

**Never dump a list of questions.** Show the draft hypothesis once, so the human
can see what you already believe — then ask about it **one question per
message**, wait for the answer, write it down, and ask the next. Follow up when
an answer opens something up; skip the questions an answer just made pointless.

There will be many questions before the picture is complete — that is expected
and it is a one-time investment. But fifteen questions asked one at a time is a
conversation someone will actually finish; fifteen questions asked at once is a
form they will abandon halfway through.

Record each answer as you get it (in the model file, or in your notes if the
file doesn't exist yet). Never rely on holding fifteen answers in your head and
writing them up at the end — the point of asking one at a time is that each
answer is banked before the next question is asked.

Per capability, you want:

- **What problem does this solve, in product terms?** Who would notice if it
  vanished tomorrow?
- **Status** — pick one:
  - `core` — the product exists to do this
  - `supporting` — core doesn't work without it, but it isn't the point
  - `nice-to-have` — real, used, but the product survives without it
  - `legacy-keep` — mostly obsolete, kept alive for one specific reason (record
    the reason — that reason is the thing you delete it with, later)
  - `dead` — nothing depends on it, nobody uses it, it just hasn't been removed
  - `unknown` — you asked and nobody is sure; say so rather than guessing
- **Planned fate** — anything the human already knows is going away, being
  replaced, or being extended.
- **Traps** — the "don't touch that, it looks wrong but it's load-bearing" facts.

Ask about **capabilities, not lines**. "What does this export module do, and
is it still needed at all?" is a good question. "Why does this 12-line function exist" is not.

Good questions to reuse:

- "These three look like they do the same thing. Do they?"
- "Is this still used, or did it just stay?"
- "If I delete this, what breaks and who notices?"
- "What here do you yourself consider junk?"
- "Which of these is the core of the product, and which is just nice to have around?"
- "What were you going to rip out but never got to?"

### 3. Write the model

Use `references/template.md`. Rules:

- **Write the model in English**, whatever language the interview was conducted
  in. Ask the questions in the human's language; write the answers down in
  English. The model is a durable artifact and gets read by people who were not
  in the conversation.
- Product language. If a line only makes sense to someone reading the source,
  rewrite it.
- One entry per capability, not per file. Point at the code (paths), don't
  reproduce it.
- Record **uncertainty honestly** — `unknown` is a legitimate status and is far
  more useful than a confident wrong claim.
- Keep it small enough to read in one sitting. A model nobody reads is dead
  weight; aim for one screen per major area.

### 4. Hand it back

Summarise in chat what surprised you — especially anything you found that looks
`dead` or duplicated. That summary is often immediately actionable.

---

## Using a model

At the start of work on a project that has one, **read it before touching
code**, and let it decide weight:

- Changes near `core` deserve care, tests and questions.
- `nice-to-have` and `legacy-keep` are candidates for deletion whenever they get
  in the way — propose it rather than working around them.
- `dead` entries can be removed on sight once the human confirms once.
- If the code contradicts the model, the model is stale — say so and ask; don't
  silently trust either one.

## Keeping it current

Update the model in the same session that changes the project:

- New capability shipped → new entry, with its status and its tests.
- Capability superseded → change status (usually to `dead` or `legacy-keep` with
  a reason) or delete the entry outright.
- Something you assumed turned out wrong → fix the entry, don't leave the lie.

A model that drifts is worse than no model, because it gets trusted. If you
cannot update it honestly (you don't know the new status), mark it `unknown`
and note the date.
