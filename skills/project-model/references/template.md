# MODEL.md template

Copy this shape. Delete sections that don't apply. Keep it readable in one
sitting — brevity is a feature.

```markdown
# <Project name>

**What it is for:** one or two sentences, in product terms. If someone asked
"why does this exist", this is the answer.

**Who uses it:** the human alone / a team of N / customers / a bot.

**Stage:** experiment | in use, low stakes | in use, people depend on it.

**Model last updated:** YYYY-MM-DD

---

## Capabilities

### <Capability name>
- **Solves:** the problem, in product terms.
- **Status:** core | supporting | nice-to-have | legacy-keep | dead | unknown
- **Lives in:** `path/to/dir`, `path/to/file.ts`
- **Proven by:** `tests/foo_test.py::test_bar` — or `none` (and whether that's OK)
- **Notes:** traps, planned fate, why it's kept if `legacy-keep`, who asked for
  it, anything a newcomer would get wrong.

### <Next capability>
...

---

## Known dead weight

Things confirmed obsolete but not yet removed, with the reason they survive.
This is the shopping list for the next cleanup pass.

- `path/to/thing` — superseded by <capability>, kept only because <reason>.

---

## Decisions worth remembering

Choices that would be expensive to reverse, and why they were made. Two lines
each, no essays.

- <Decision> — because <reason>. Reversing means <cost>.

---

## Open questions

Things the model does not know. Ask them next time the human is in the loop.

- <question>
```

## Filling rules

- **Product language.** "Splits trip expenses between participants and settles
  debts" — not "exposes a REST controller wrapping the ledger service".
- **One entry per capability**, not per file, not per class.
- **`Proven by` matters.** A `core` capability with no test is a finding —
  mention it. A `nice-to-have` with three test files is a finding too.
- **`unknown` is allowed and encouraged.** A model that admits gaps stays
  trustworthy.
- **Point, don't copy.** Paths, not pasted code. The code changes; the model
  should only change when the *purpose* changes.
