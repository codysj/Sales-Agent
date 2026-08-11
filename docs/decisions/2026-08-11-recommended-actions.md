# Recommended actions — 2026-08-11

- **Prepared for:** the project owner, as the input to a decision session.
- **Baseline:** commit `db78a8f`, working tree clean.
- **Status of everything below: RECOMMENDED, not decided.** Nothing here answers a specification
  `Q-###`, records a stakeholder decision, or unlocks a gate. Each item states what it would take
  to close it and who has to say so.

This document exists because the project has reached the point where the **binding constraints are
no longer engineering ones**. Stage 1 and Stage 2 are built; what stands between here and anything
further is one small defect, one observed session, and a set of business answers nobody has been
asked for yet.

---

## The shape of the problem, in one paragraph

The repository can do everything it is allowed to do. The pipeline runs end to end on synthetic
fixtures, a reviewer can work a queue, and every external effect is deliberately closed. The next
gate (**G-10**) does not ask for more code — it asks whether a person who does not understand the
system can use it. That question cannot currently be *asked*, because the dashboard's API calls are
blocked by the browser (item 1). Past that gate, everything is waiting on product and commercial
input that has a longer lead time than any of the engineering work left.

---

## Summary

| # | Item | Type | Gates | Recommendation | Who decides |
|---|---|---|---|---|---|
| 1 | Dashboard API calls blocked cross-origin | Defect | G-10, both rehearsal paths | Fix with a dev-server proxy | Engineering (approve to proceed) |
| 2 | The Stage 2 rehearsal | Evidence | G-10 → Stages 3–7 | Run the agent pass now, the human pass before Stage 4 | Owner (schedule) |
| 3 | `Q-005` — who may approve | Decision | G-08; surfaces at the rehearsal | Name one commercial approver now | Owner |
| 4 | `Q-021`/`Q-022`/`Q-017` — product brief and claims | Decision | G-08; quality of everything | Commission one brief, sodium battery | Owner + product |
| 5 | `Q-018` — hosting and post-internship owner | Decision | Production, `T-086`, `T-185` | Answer the ownership half now | Owner |
| 6 | `T-164b` — nobody has read a CI run | Verification | Ledger accuracy | Install `gh`, or paste the result | Owner (one command) |
| 7 | `T-009` — stakeholder acceptance record | Record | Stage 0 closure narrative | One dated paragraph | Owner |
| 8 | `T-183` — may the pinned spec be edited? | Authority | Recording future answers | Do not edit; use dated addenda | Owner |
| 9 | `Q-004`/`Q-026` — mailbox and identity provider | Decision | G-07, real auth | Defer, but check tenant availability | Owner |

**If only three things happen this week:** item 1 (an hour), item 2's agent pass (same day), and
item 4's brief request (because it is the longest pole and nothing else shortens it).

---

## 1. The dashboard's API calls are blocked by the browser

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

**Do the agent pass now** (it is same-day once item 1 lands, and its findings will improve the
screens before a person ever sees them), and **schedule the human pass before Stage 4**.

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

## What is deliberately *not* recommended

Recorded so these are not re-opened as oversights.

- **`T-165`** (frontend dependency overrides) — `READY`, and there is nothing to do. `next@latest`
  was re-measured and has not moved. Leave it; it is correct to revisit only when the release does.
- **`T-094`** (fake CRM adapter) — `READY`, and it should not be started. Its only consumer,
  `Rule.EXISTING_RELATIONSHIP`, is gated at **G-05**, and the suppression half is already served by
  `find_suppression`. Building it now produces an interface with one implementation and no call
  site.
- **Any Stage 3 engineering before item 1 and item 2's agent pass.** The gate is not a formality;
  building the evaluation harness first would mean measuring a system whose reviewer-facing half is
  unproven.
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
