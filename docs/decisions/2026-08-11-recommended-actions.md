# Recommended actions — 2026-08-11

- **Prepared for:** the project owner, as the input to a decision session.
- **Baseline:** commit `db78a8f` plus the working tree.
- **Status of everything below: RECOMMENDED, not decided.** Nothing here answers a specification
  `Q-###`, records a stakeholder decision, or unlocks a gate. Each item states what it would take
  to close it and who has to say so.

> **Revised later the same day (`T-202`).** The first version of this page was accurate when
> written and went stale within hours, in the direction that misleads: it presented finished work
> as outstanding and omitted a decision that had since become blocking. What changed:
>
> - **Item 1 is closed.** The dashboard's cross-origin defect was fixed by `T-195`; a reviewer has
>   since signed in and worked the queue in a real browser.
> - **Item 2 has acquired a blocker.** The agent rehearsal is not "schedulable now" — it needs a
>   decision first. See item 2.
> - **Item 10 is new** and is now one of the two things everything is waiting on.
> - **Item 11's `T-165` entry was wrong** and is corrected there.
>
> **Two decisions are currently blocking every other task in the repository: items 2 and 10.**

This document exists because the project has reached the point where the **binding constraints are
no longer engineering ones**. Stage 1 and Stage 2 are built; what stands between here and anything
further is one small defect, one observed session, and a set of business answers nobody has been
asked for yet.

---

## The shape of the problem, in one paragraph

The repository can do everything it is allowed to do. The pipeline runs end to end on synthetic
fixtures, a reviewer can work a queue in a real browser, and every external effect is deliberately
closed. The next gate (**G-10**) does not ask for more code — it asks whether someone who does not
understand the system can use it.

**As first written, that question could not be *asked*** because the dashboard's API calls were
blocked by the browser. That is fixed (item 1). **It now cannot be asked for a different reason:**
the only rehearsal path that needs no calendar requires an agent to perform an approval, and that
is prohibited until you say otherwise (item 2). A second decision, about a dependency writing into
the instruction channel, arrived alongside it (item 10).

So the shape has changed from *one defect and a scheduling problem* to **two decisions and a
scheduling problem**. Past the gate, everything is waiting on product and commercial input with a
longer lead time than any engineering work left.

---

## Summary

| # | Item | Type | Gates | Recommendation | Who decides |
|---|---|---|---|---|---|
| ~~1~~ | ~~Dashboard API calls blocked cross-origin~~ | **CLOSED** | — | Fixed by `T-195` — dev-server proxy, browser-verified | done |
| **2** | **The Stage 2 rehearsal — now blocked on a decision** | **Decision** | **G-10 → Stages 3–7** | **Allow the agent pass on a throwaway database** | **Owner** |
| **10** | **A dependency writes into the instruction channel** | **Decision** | Protocol integrity | **Option (c): ignore, state the rule, pin the root file** | **Owner** |
| 3 | `Q-005` — who may approve | Decision | G-08; surfaces at the rehearsal | Name one commercial approver now | Owner |
| 4 | `Q-021`/`Q-022`/`Q-017` — product brief and claims | Decision | G-08; quality of everything | Commission one brief, sodium battery | Owner + product |
| 5 | `Q-018` — hosting and post-internship owner | Decision | Production, `T-086`, `T-185` | Answer the ownership half now | Owner |
| 6 | `T-164b` — nobody has read a CI run | Verification | Ledger accuracy | Install `gh`, or paste the result | Owner (one command) |
| 7 | `T-009` — stakeholder acceptance record | Record | Stage 0 closure narrative | One dated paragraph | Owner |
| 8 | `T-183` — may the pinned spec be edited? | Authority | Recording future answers | Do not edit; use dated addenda | Owner |
| 9 | `Q-004`/`Q-026` — mailbox and identity provider | Decision | G-07, real auth | Defer, but check tenant availability | Owner |

**If only three things happen this week:** answer item 2 (one decision, unblocks the whole critical
path), answer item 10 (one decision, protocol integrity), and request item 4's product brief —
because it is the longest pole and nothing else shortens it.

**Nothing in this repository can move until items 2 and 10 are answered.** Every other task is
either finished, blocked on a stakeholder question below, or deliberately not worth starting.

---

## 1. The dashboard's API calls are blocked by the browser — ✅ CLOSED

> **Resolved 2026-08-11 by `T-195`, hours after this was written.** The dev-server proxy was the
> option taken: `next.config.ts` rewrites `/api/*`, `/healthz`, and `/readyz` to the backend, and
> the client fetches relative paths, so no cross-origin request exists to permit and the API
> gained no `Access-Control-Allow-Origin` path. A reviewer then **signed in and worked the review
> queue in a real browser** — three candidate rows, a card opened complete with evidence and all
> five actions, every request same-origin. That had never been observed before.
>
> `T-200` later pinned the rewrite itself, after finding that deleting it left the entire suite
> green and the dashboard unusable. **No action required from you.** The rest of this section is
> kept as the record of what the defect was.

**Type:** defect, unfiled until now. Now filed as **`T-195`**.

### What is wrong

The dashboard is served from `http://localhost:3000` and its client components fetch the API at
`http://localhost:8000`. That is a cross-origin request. `backend/app/main.py` registers no CORS
middleware, and `frontend/next.config.ts` declares no rewrite, so the browser refuses every one of
them. `frontend/app/review/page.tsx` is a `"use client"` component; the fetches happen in the
browser, not on the Next.js server.

The Stage 2 exit evidence recorded every dashboard page answering `200`. That measurement was
correct and is not the same thing: it exercised **server-side page rendering**, not the API calls
those pages make once they reach a browser. The README already documents the gap honestly; the
ledger simply never carried a task for it.

### What it gates

Both rehearsal paths, therefore **G-10**, therefore Stages 3 through 7. A reviewer — human or
agent — reaches the sign-in screen and cannot get past it.

### Recommendation: a dev-server proxy, not CORS middleware

Add a rewrite to `frontend/next.config.ts` mapping `/api/*` to `http://localhost:8000/api/*`, and
point `lib/api.ts` at a relative base URL. Roughly five lines in two files.

**Why this rather than adding CORS middleware to the API:**

- **One origin means the problem disappears rather than being permitted.** There is no
  cross-origin request left to allow.
- **It protects the cookie work already done.** `T-070a` landed `HttpOnly`/`SameSite`/`Secure`
  session cookies and CSRF echo checks. A `SameSite` cookie is not sent cross-site; making the
  dashboard same-origin keeps that design intact, whereas a CORS allowance would push toward
  relaxing it.
- **It adds no permissive header path to a safety-critical API.** In a codebase whose entire
  posture is that external effects are structurally closed, an `Access-Control-Allow-Origin`
  branch is a thing a future reader has to reason about. A dev-server rewrite is not.
- **It is confined to the development server.** The rewrite lives in the frontend's own config and
  is a Stage 2 local-development concern, exactly the scope `lib/api.ts`'s `assertLocal` already
  enforces.

**What is deliberately not being done:** a production ingress or reverse-proxy design. That is
`Q-018`'s territory (item 5) and inventing it now would be building deployment architecture for an
environment nobody has decided on.

**Needed from you:** approval to make the change. It is a small, reversible, test-covered edit; it
has not been made because the ask was to document, not to implement.

---

## 2. The Stage 2 rehearsal — and the agent-team path

**Type:** evidence. **Tasks:** `T-071b` (human), **`T-071c`** (agent team, new).

### The gate, and the honest problem with it

**G-10** asks: *a non-engineer completes reviews without understanding the agent stack.* It has sat
locked because it needs a person, an hour, and no explanation.

You asked whether a sophisticated pass by an LLM agent team can satisfy it. The direct answer is
**partly, and the split matters** — which is why this is recorded as **ADR-030** rather than as a
wording change.

An agent team with genuinely fresh context, given only the reviewer-facing page and no access to
this repository, tests something real and tests it *better* than one human does:

- Whether the setup path works from cold, followed literally.
- Whether the screens are self-explanatory without knowing the architecture.
- **Where comprehension breaks** — and across many independent runs rather than one, which is a
  stronger signal about the interface than a single session gives.
- Whether the closing question (*what happens to the one you approved?*) is answerable from the
  screens alone.

What it cannot do, and no prompt makes it do:

- **Be a person.** The gate's purpose is not to test a reader; it is to establish that the humans
  who will eventually approve real messages to real people *can*. An agent's fluency with unfamiliar
  software is unrepresentative in the optimistic direction — it will not misread, skim, give up, or
  bring the impatience a real reviewer brings.
- **Carry accountability.** The safety model rests on a human approving. Evidence that an agent
  completed the flow is not evidence that the approval authority is workable.

### Recommendation: two paths, unlocking different amounts

Recorded in **[ADR-030](../adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md)** and applied
to the gate row in `tasks.md` §5.

| Path | Task | Unlocks |
|---|---|---|
| **Agent-team rehearsal** | `T-071c` | **G-10 for Stage 3 only** — evaluation harness, correctness suite, adversarial safety suite. Internal, synthetic, reversible work. |
| **Human rehearsal** | `T-071b` | **G-10 fully.** Required before any Stage 4/5 work, and a hard precondition of G-07 and G-08. |

This is not a formality split. Stage 3 is entirely internal measurement of a synthetic system; if
the interface evidence behind it turns out to be optimistic, the cost is rework on a test harness.
Stage 5 onward touches real mailboxes and real recipients, and the question of whether a human can
actually operate the approval screen stops being an interface question and becomes a safety one.

> ### ⛔ The agent pass is blocked on a decision, and this is one of the two the repository is stopped on
>
> Discovered when the loop went to start `T-071c`. **The rehearsal asks its subject to approve a
> candidate** — Part B step 2, "for at least one, decide yes" — and half the gate is reviewing the
> message that approval produces. So running it means **an LLM agent performing an approval in the
> dashboard**, which writes an `Approval` row and an audit event.
>
> `tasks.md` §5 lists *"any model or agent approving or executing an action"* under prohibited
> starts as **REJECTED** — not gated, rejected. `AGENTS.md` rule 5 says the same. Those are the
> strongest prohibitions in the repository and only you may move them.
>
> **The case it is fine:** shadow mode is on, G-07 is locked, the candidate is synthetic, nothing
> sends. §3.5's actual invariant is *"zero external execution authority held only by the agent
> runtime"* — about an agent being **wired in** as an authority, which this is not. The agent holds
> no credential and drives a browser exactly as a person would.
>
> **The case against, which is the better one:** it writes approval records attributed to a
> reviewer account that no human made, into the same table, unmarked.
>
> **Recommended: allow it, with two conditions** — run against a **throwaway database that is
> dropped afterwards**, so no agent-made approval survives anywhere an audit would read, and record
> in the exit evidence that those approvals were agent-made. That keeps the architectural invariant
> (never at risk) and closes the record-integrity objection (the real one). If you agree, §5 wants
> one sentence distinguishing *an agent wired in as an approval authority* — rejected permanently —
> from *an agent operating the dashboard as a test subject in shadow mode*. ADR-030 should be
> amended with whichever way you decide; it did not consider this.

Once that is answered, **do the agent pass** — its findings will improve the screens before a
person ever sees them — and **schedule the human pass before Stage 4**.

The protocol for the agent path is Part D of
[stage2-rehearsal-script.md](../stage2-rehearsal-script.md). Its design constraints — fresh context
per agent, no repository access, at least three independent runs, verbatim transcripts, and an
explicit refusal to let any agent that read the codebase count — exist so that the result is
evidence rather than a system grading its own homework.

**Needed from you:** approval of the two-path split (ADR-030), and a date for the human pass.

---

## 3. `Q-005` — who may approve product claims, candidates, and messages

**Type:** stakeholder decision. **Spec:** §20.1. **Hard-blocks:** G-08.

The RBAC machinery exists and works; what does not exist is a roster. The checkpoint's assumption
**A6** records that a synthetic operator suffices for G-10, so this does **not** block either
rehearsal — but the rehearsal will raise it in the room, because the first question a thoughtful
reviewer asks is *"am I actually allowed to decide this?"*

### Recommendation: name one commercial approver now, in writing

One person, by name and role, with authority over outbound product statements. Not a committee and
not a process — a name.

**Why now rather than at G-08:** it costs one sentence today and it is on the critical path of
three separate things later (`T-021`, `T-062`, `T-067`). It also determines whose judgement the
approved-claim set in item 4 has to survive, so answering it first makes that request cheaper.

`Q-025` — who owns and reviews the product-status and approved-claim store — is the same
conversation and should be answered in the same sentence. Frequently it is the same person.

---

## 4. `Q-021`, `Q-022`, `Q-017` — an approved product brief and claim set

**Type:** stakeholder decision. **Hard-blocks:** G-08, and the credibility of everything measured
before it.

### Why this is the longest pole

Every product fact in the repository is synthetic, and deliberately so: a test asserts that **no
fixture string contains a digit**, precisely so that no placeholder can ever be mistaken for a real
specification, price, certification number, or roadmap date. That is a good rule and it has a
consequence — there is currently no real product statement the system could ever emit, because
drafting may only cite an approved claim and no approved claim exists.

It also caps what Stage 3 can tell you. The evaluation harness will measure the system against
fixtures; it cannot measure whether the system says true and useful things about a real product
until there is a real product description to be true about.

### Recommendation: commission one brief, for the sodium battery pack

Not both campaigns. `Q-023` is already decided — build both, pilot one — and the DC fast-charging
solution (`Q-022`) is the broader, slower document. One brief covering:

- Specifications, readiness, and availability.
- Certifications held, and applications approved for.
- Which claims may be stated externally, and in what words (this is `Q-017`, and it is the part
  that must be *versioned* — the system pins an approved claim set to every approval).
- Pricing posture, even if the answer is "do not state price".

**Why one and not two:** the pilot runs one campaign regardless, a second brief doubles the review
burden on whoever item 3 names, and nothing downstream needs the second until Stage 6.

`Q-002` — segments and buyer roles — should ride along in the same request. It is the last input
needed by `T-145`, the remaining unimplemented hard-eligibility rule, and without it the ICP
exclusions have to stay stubbed.

---

## 5. `Q-018` — where does this run, and who owns it after the internship

**Type:** stakeholder decision. **Blocks:** `T-086` (staging), `T-185` (deployment registration),
and is recorded in the specification as a production blocker.

Flagged now for lead time, not urgency. Two concrete consequences already exist:

- **`T-185` is a real, filed hole.** The prompt, schema, and model-config versions that every
  qualification job resolves are registered only by `seed_synthetic`, which refuses to run outside
  `local`/`test`. The first real deployment would fail permanently on its first qualification job.
  The fix cannot be designed until "what is a deployment here" has an answer.
- **The npm advisory posture depends on it.** The checkpoint's assumption **A10** records that the
  dashboard's advisories are unexploitable *because it is local-only*. That becomes false the moment
  anything is deployed.

### Recommendation: answer the ownership half now, defer the hosting half

"Who maintains this after the internship ends" is answerable today and is the more important half.
If the honest answer is *nobody yet*, that is worth knowing **before** Stage 3 evaluation work is
built, because the value of a measurement harness depends entirely on someone being there to act on
what it measures.

Hosting can wait for the mailbox decision (item 9) — they are likely to resolve into the same
Microsoft-tenant conversation.

---

## 6. `T-164b` — nobody has read a CI run

**Type:** verification gap. **Status:** `READY` and has been for ten days.

CI has run on `origin/main` at least once. Nobody has looked at the result, because `gh` is not
installed on this machine and the loop cannot reach the Actions tab. A full local dry run of every
command in the workflow passed on 2026-08-01, which removes the ordinary reasons a first run goes
red — a stale lockfile, a migration divergence, a type error — but it was Windows against local
Docker, not `ubuntu-latest` against the workflow's service container, and `npm ci` was a dry run.

### Recommendation: install the GitHub CLI

```bash
winget install GitHub.cli
```

Then the run can be read, recorded, and the task closed in one pass. Pasting the outcome works
equally well. Low stakes — but the ledger currently asserts a CI pipeline whose first real run
nobody has confirmed, and that is the kind of small untrue thing that erodes trust in the larger
claims around it.

---

## 7. `T-009` — the stakeholder acceptance record

**Type:** record. **Status:** `BLOCKED`, correctly, since the beginning.

Stage 0's exit gate is written stakeholder acceptance of the architecture contract: that the
application owns the workflow, the dashboard owns approval, messaging is complementary, OpenClaw is
optional and isolated, and one campaign goes live first. The specification header declares v0.3
approved for buildout, but no acceptance record exists in the repository, and the loop has correctly
refused to invent one.

### Recommendation: one dated paragraph, from whoever accepted it

Names, roles, date, and the forum. It goes in `docs/decisions/architecture-contract-acceptance.md`,
the path `T-009` already names. This is five minutes of writing and it closes the only outstanding
Stage 0 item, plus reconciliation item **R-002**.

---

## 8. `T-183` — may the pinned specification be edited?

**Type:** authority. **Status:** `BLOCKED` on your say-so.

The specification is pinned by hash: `tasks.md` and `AGENTS.md` both record its SHA-256 and byte
size, and a test recomputes and compares them. Recording an answered `Q-###` in §20.1 would break
that property deliberately and require refreshing the hash in two places.

### Recommendation: do not edit it — use dated addenda

Keep answers in `docs/decisions/`, dated, with the ledger's §6 pointing at them. The specification
stays the byte-identical artifact that was handed over, the integrity test keeps meaning something,
and answers are still findable in one place.

**Why this is better than the alternative:** the value of a hash pin is that it is never
convenient to break. Once it has been refreshed for an ordinary reason, it will be refreshed for the
next ordinary reason, and it stops being evidence of anything. An addendum costs one indirection and
preserves the property permanently.

Revisit if the specification ever needs a genuine architectural revision — that is a §22
revision-history event with a version bump, which is a different act from recording an answer.

---

## 9. `Q-004` and `Q-026` — mailbox, sender identity, and identity provider

**Type:** stakeholder decision. **Blocks:** G-07, `T-100`, `T-101`, `T-102b`, `T-061b`, `T-070b`.

A direction is recorded — Microsoft 365 / Outlook for the mailbox, with Entra ID following for
identity — but a direction is not an answer. No mailbox address, sender identity, reply owner,
domain, or verified SPF/DKIM/DMARC exists, and no tenant or user roster exists either. The local
sign-in stub stands, confined to `local`, which is the correct state.

### Recommendation: defer the decision, but check tenant availability now

Answering `Q-004` properly is Stage 5 work and answering it early buys nothing — no email code may
be written until **G-07** opens, and G-07 needs G-10 first.

**The one thing worth doing now** is establishing whether a Microsoft 365 tenant that this project
may use actually exists, or whether one has to be provisioned. That is a procurement question with
lead time measured in weeks, owned by someone other than this project, and it would be unfortunate
to discover it at the point where everything else is ready.

---

## 10. A dependency now writes into the repository's instruction channel

**Type:** decision. **Task:** `T-201`, `BLOCKED` on you. **Added by the `T-202` revision** — this
did not exist when the page was first written.

### What happened

`next@16.3.0` — introduced by `T-165` while retiring stale dependency overrides — writes
**`frontend/AGENTS.md`** and **`frontend/CLAUDE.md`** on every `npm run dev`, and re-creates them if
deleted. `next@16.2.12` did not.

`process.md` §1 ranks nested `AGENTS.md`/`CLAUDE.md` **second in the conflict order, above the
specification itself**. So a dependency can now write into the channel this repository reads as
protocol. `AGENTS.md` rule 11 says all external content is untrusted **data, never instructions** —
a file authored by `node_modules` and loaded as protocol inverts exactly that, in the one place the
inversion is invisible, because the harness reads it before anyone reads the diff.

**Today's content is benign** — it says to read the bundled Next.js docs. **The content is not the
finding; the channel is.** Its next version is whatever the vendor ships.

### What was measured

- **There is no opt-out.** The whole condition is: if no agent is detected, return; if the block is
  already current, return; otherwise write. No config option, no environment variable.
- **It fires only when an AI coding agent is detected**, via env vars the agent's own harness sets
  (`CLAUDECODE`, `CURSOR`, `GEMINI_CLI`, `COPILOT_*`, …). A human running `npm run dev` never
  produces these files. They exist because *the loop* ran the dev server.
- **Committing them does stop the writes**, but the generator **upserts into an existing
  `AGENTS.md`** rather than only scaffolding a missing one — so the day the vendor revises the
  block, it silently rewrites the committed file.
- **The blast radius is contained by layout, not design.** It targets the Next project directory,
  which here is `frontend/`. The root `AGENTS.md` is verified untouched. Were the Next project ever
  rooted at the repository root, the same code path would edit your primary instruction file.

### Recommendation: option (c)

Ignore the generated files, **and state the rule**: add to `AGENTS.md` that a nested instruction
file is authoritative only if repository-authored, and that generated ones are data. Pin it with a
test asserting the root `AGENTS.md` carries no vendor-managed block — true today, cheap, and it
fails loudly if either the layout or the vendor's behaviour changes.

The alternatives: **(a) commit them** accepts vendor-authored text into the protocol permanently and
makes every `next` upgrade a protocol diff someone must read as protocol; **(b) gitignore only**
cleans the tree but hides the mechanism, since the file is still loaded whenever it exists; **(d)
disable the generator** is not available — measured, no switch exists.

The loop deliberately did not choose. It is protocol, and an agent should not rule on what may
write to its own instruction channel — least of all by picking the option that makes its tree clean.

---

## What is deliberately *not* recommended

Recorded so these are not re-opened as oversights.

- ~~**`T-165`** (frontend dependency overrides) — nothing to do.~~ **This was wrong, and the way it
  was wrong is worth keeping.** The claim rested on a measurement taken once and then re-asserted
  for ten days instead of re-taken. Re-measuring found `next@latest` had moved to `16.3.0`, which
  retired **three of the four** overrides — and that the expiry conditions written beside them named
  the override's own version rather than the advisory's ceiling, so following the note would have
  kept an override alive past its reason. `T-165` is `DONE`. A task whose whole subject was "a
  standing instruction nobody expires" had itself been kept alive by an unexpired measurement.
- **`T-094`** (fake CRM adapter) — `READY`, and it should not be started. Its only consumer,
  `Rule.EXISTING_RELATIONSHIP`, is gated at **G-05**, and the suppression half is already served by
  `find_suppression`. Building it now produces an interface with one implementation and no call
  site.
- **Any Stage 3 engineering before item 2's agent pass.** The gate is not a formality; building the
  evaluation harness first would mean measuring a system whose reviewer-facing half is unproven.
- **A production deployment design.** Blocked on `Q-018` by intent, not by omission.

---

## One thing worth saying plainly

The system has never been assessed for whether its output is any *good*. Every qualification and
draft in the repository comes from a deterministic fake reading fixture files — which is why all
three seeded candidates return an identical `pilot` recommendation. That is the fake being a fake,
not the system forming a view.

"It works" currently means **the machinery is correct**: the state transitions hold, the approvals
pin what they must, nothing escapes, and the audit trail is complete. Whether the thing it produces
is worth sending to anyone is a Stage 3 question behind **G-10** and `Q-012`, and no amount of the
current evidence speaks to it. That distinction is worth carrying into any conversation about
timelines.
