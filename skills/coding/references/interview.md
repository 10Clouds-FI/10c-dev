# Interview question bank

**This is a bank to draw from, not a script to read out.** Ask ONE question,
wait for the answer, then decide what to ask next — including follow-ups the
bank doesn't contain. Never paste a numbered list of questions at someone.

Concrete beats open-ended: "web, mobile or a Telegram bot?" gets an answer;
"what are the requirements?" gets a shrug.

## Always, in one form or another

- **What problem is this solving?** Not "what should it do" — what goes wrong
  today without it.
- **Who uses it?** You alone, a team, a client, strangers on the internet? That
  single answer decides auth, error handling, and polish.
- **How do they get to it, and what state are they in when they arrive?** A link
  you send them, a tab inside something they are already logged into, a command
  they run, a file you hand over. Then: logged in or logged out, your machine or
  theirs, first time or returning. This is the question that is skipped most and
  costs most — the human pictures a door you never saw, and everything you built
  works only through your own.
- **What does done look like?** The moment you'd say "yes, that's it".
- **How long should this live?** Throwaway experiment, weekend tool, or
  something that has to survive a year.
- **Will this go to `main`?** If yes it is R2 at least (tests first, review),
  and a ticket exists before any code. If it touches tenant isolation, authz,
  migrations, pipelines or the chat gateway, say so now: the critic is mandatory (as it is near a core capability).

## Anything a person will open (page, link, app, file you hand over)

Ask these the moment a human other than you might touch it. They decide whether
the thing works at all for the person who opens it — not whether it works on
your machine.

- Who opens it, and do you send them the address or do they find it inside
  something they already use?
- Is it forwarded onwards — to a client, into a chat, in an email?
- What should the first arrival look like for someone who is NOT you and NOT
  logged in: a login page and then the thing, a refusal, or open to anyone?
- Does it have to keep working tomorrow, next month, after they change laptops?
- What must NOT be visible to whoever gets the address by accident?

## New thing from scratch

- Shape: web app / mobile / CLI / script / Telegram bot / browser extension /
  library / cron job?
- Where does it run: your laptop, a VPS you already have, a hosted platform,
  someone else's machine?
- Is there existing stack to match, or is this greenfield? Language preference?
- Does it need to persist anything between runs? If yes, how much would you
  lose if it vanished — file, SQLite, real DB?
- Does anyone else need to log in? (Usually the answer is no, and that removes
  half the work.)
- Is there an existing thing it should look/behave like?

## Feature in an existing codebase

- Which flow does this attach to — walk me to the entry point.
- Should it replace something that exists, or live alongside it?
- Who currently depends on the behaviour you're about to change?
- Is there an existing pattern in this repo I should copy rather than invent?
- Does this need to keep working for existing data / existing users?
- Anything in this area you already know is broken or dead?

## Bug fix

- What did you expect, what happened instead, and how do I reproduce it?
- When did it last work? Anything change around then?
- Is the fast fix acceptable, or do you want the root cause?
- What is the smallest case that reproduces it? That becomes the first test,
  written before the fix (R2+ always; it is not optional there).

## Refactor / cleanup

- What is the actual pain — reading it, changing it, or it being wrong?
- What must not change from the outside?
- Is there test coverage I can lean on, or do I need to build a safety net first?
- How far do you want this to go — this file, this module, or the pattern
  everywhere?

## Scope-cutting questions (the most valuable ones)

- Which of these do you want *now* and which are "eventually"?
- If we could only ship one part of this today, which part?
- Is it OK if this is ugly for now?
- Is it OK if this only handles the happy path?

## Contributions to offer alongside the questions

Only when genuinely relevant, max ~5, one or two sentences each:

- **Failure mode they haven't pictured** — concurrency, restarts, rate limits,
  someone typing a comma into a number field, the second user.
- **The boring standard approach** — if their plan diverges from how this is
  normally done, name the standard and ask whether the divergence is intended.
- **A cheaper path** — "there's a library that does exactly this", "we can fake
  this part until it matters", "20 lines get you 80% of it".
- **A real tradeoff** — two viable shapes and the consequence of each, with a
  recommendation. Not a menu; an opinion.
- **A decision that will be expensive to reverse** — data format, public API
  shape, anything other people will build on. Flag these early; everything else
  can be changed later.

Filler to avoid: restating the request back as a "question", asking about
things with obvious defaults, asking for permission to think.
