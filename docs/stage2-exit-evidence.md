# Stage 2 exit evidence

- **Recorded:** 2026-08-01
- **Task:** `T-071a` (the walkthrough). The rehearsals are `T-071b` (human) and `T-071c` (agent
  team) — two evidence paths that unlock different amounts, per
  [ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md).
- **Gate:** **G-10** — specification §19.6, Stage 2: *"A non-engineer completes reviews without
  understanding the agent stack."*
- **Status: the gate is NOT evaluated here, and this document does not claim it is met.** What
  follows is a script that has been *executed*, not a rehearsal that has been *observed*. §5 below
  is deliberately empty: nobody, and nothing, has run this. Filling it in is `T-071b`/`T-071c`, and
  until then **G-10 stays LOCKED.**

Every command and every number below was observed on the date above, against databases created for
the run and dropped afterwards. Nothing is reconstructed, estimated, or copied from a test.

## What the gate asks, and what this document can answer

| §19.6 requirement | Answered by |
|---|---|
| The setup a reviewer needs works from clean | [§1](#1-the-setup-path), [§2](#2-what-the-database-holds-afterwards) |
| A reviewer can sign in and reach their work | [§3](#3-signing-in-and-the-reviewers-routes), [§4](#4-the-dashboard) |
| …**without understanding the agent stack** | **Nobody has tried yet — [§5](#5-the-rehearsal-not-done)** |

The third row is the gate. The first two are its preconditions, and they are what `T-071a` owns.

## 0. Before you start

You need Docker, [uv](https://docs.astral.sh/uv/), and Node 22. From the repository root:

```bash
docker compose up -d db
```

PostgreSQL 16 on host port **55432** (`docs/development.md` explains the port choice). Copy
`.env.example` to `.env` and leave every value as it is — the defaults are local throwaway values
and the safety switches default to the safe position.

**Nothing in this document sends anything.** Shadow mode is on, outbound email is off, the model is
a deterministic fake reading files from `backend/app/fixtures/`, and every command below refuses to
run unless `APP_ENV` is `local` or `test`. There is no credential to supply and nowhere to supply
one.

## 1. The setup path

Six commands, in this order, from `backend/`. This is the whole of it.

```bash
uv run alembic upgrade head
uv run python -m app.cli seed_synthetic
uv run python -m app.cli start_campaign synthetic-sodium-battery
uv run python -m app.cli import_prospects
uv run python -m app.cli run_worker
uv run python -m app.cli grant_local_reviewer
```

Run 2026-08-01 against a throwaway database, all six exiting `0`. The output is JSON, one line per
event; the interesting fields are quoted below.

**`alembic upgrade head`** — 30 migrations, `3c526b2ea3ca` (initial empty baseline) through
`a17e5c4b8d20` (a contact records the import batch it came from).

**`seed_synthetic`** — `was_noop: false`, and `created` lists 29 things. Two campaigns with their
products, readiness versions, segments, policy versions, and approved claim sets; the approver
`synthetic-approver@example.invalid`; and the versions every model task resolves for itself:

```
"prompt version draft", "prompt version qualification",
"schema version draft-output", "schema version qualification-output",
"model config qualification-model-config", "model config draft-model-config"
```

Running it a second time reports `created: []` and changes nothing.

**`start_campaign synthetic-sodium-battery`** — `already_running: false`. Seeded campaigns arrive
**paused** on purpose (`T-015`, §17.6): a paused campaign produces no candidates, so starting one
is a deliberate act rather than a side effect of seeding. Only the sodium campaign is started
here; §2 shows what that costs the other one, which is the point of doing it this way.

**`import_prospects`** — `created: 14, reused: 1, rejected: 0, membership_jobs: 17`. It reads the
bundled `app/fixtures/prospects.csv` and takes no path argument, so it cannot be pointed at a real
list. Re-running reports `already_imported: true` and writes nothing.

**`run_worker`** — `passes: 40, drained_to_idle: true`. This drains the queue with the Stage 1
fakes installed and then stops, which is why it is a separate command from `python -m app.worker`
(that one loops forever and installs no fakes — see ADR-027). Observed job types, in order:
`campaigns.create_membership`, `qualification.apply_eligibility`, `campaigns.start_research`,
`research.capture_evidence`, `campaigns.complete_research`, `qualification.qualify_candidate`,
ending with three `qualify.presented_for_review` events.

**`grant_local_reviewer`** — `email: synthetic-reviewer@example.invalid`, `role: operator_reviewer`,
`user_created: true`, `role_granted: true`. That address is the one you sign in with. It is on an
IANA-reserved domain and can never be delivered to.

## 2. What the database holds afterwards

Read back from the throwaway database after the six commands, not asserted from the log lines:

| Table | Rows |
|---|---|
| `campaign` | 2 |
| `account` | 12 |
| `contact` | 13 |
| `campaign_candidate` | 8 |
| `evidence_snapshot` | 3 |
| `qualification_run` | 3 |
| `message_revision` | **0** |
| `job` | 39 |
| `prompt_version` / `schema_version` / `model_config_version` | 2 / 2 / 2 |
| `app_user` | 2 |
| `user_role` | 1 |
| `audit_event` | 111 |
| `outbox_event` | **0** |

Candidate states: **`REVIEW_PENDING: 3`**, `INELIGIBLE: 5`. Job states: `SUCCEEDED: 39` — none
queued, none dead.

Four of these numbers are worth reading rather than skimming.

- **`message_revision: 0` is correct, not a shortfall.** §8.3 presents a candidate for review at
  step 8 and drafts a message at step 9, and drafting is triggered by a human approving the
  candidate. A drain that produced messages would mean the system had written prospect-facing copy
  nobody approved.
- **`outbox_event: 0`** — nothing was queued for any external effect, which is what shadow mode is
  for.
- **`INELIGIBLE: 5`** — every one failed the `contactability` rule. That is the fixture set doing
  its job: it carries unverified and missing contact points on purpose so the eligibility rules
  have something to refuse.
- **17 membership jobs produced 8 candidates.** The missing nine belong to
  `synthetic-dc-fast-charging`, which was never started. The pause is real and it is visible here.

`evidence_snapshot: 3` comes from one account: the fixture corpus under
`app/fixtures/source_documents/` holds documents for `alpha.example.com` only, so the other two
researched candidates captured zero. They still reach review — a candidate with no evidence is a
thing a reviewer should see, not a thing to hide.

**Know this before the rehearsal: two of the three cards carry no evidence.** Measured 2026-08-02
by reading the three cards back from `GET /api/review/candidates/{id}` on a fresh run —
`SYNTHETIC-Account-Alpha` has 3 evidence items, `Foxtrot` and `Juliett` have **0**. All three carry
the same `opportunity_type: "pilot"`, because the deterministic fake answers every qualification
prompt from one fixture directory; it is not weighing the evidence, and nothing about that
sameness is a product judgement.

The card is honest about it — the Evidence section reads *"None recorded. Nothing here supports a
statement about this prospect."* (`ReviewCard.tsx`, held by
`frontend/tests/review-card.test.tsx`). But whoever runs `T-071b` should expect the majority of
what they see to look like that, and should not read three identical `pilot` recommendations as
the system agreeing with itself. If the rehearsal wants a card with evidence on it, use the
**Alpha** account.

## 3. Signing in and the reviewer's routes

With the API running (`uv run uvicorn app.main:app` from `backend/`), observed 2026-08-01 on the
same database:

```
GET  /healthz                                 -> 200 {"status":"ok","version":"0.1.0"}
POST /api/auth/stub-sign-in                   -> 200
GET  /api/auth/session                        -> 200
GET  /api/review/candidates                   -> 200   rows: 3
GET  /api/review/candidates/{id}              -> 200
GET  /api/review/attention/approvals          -> 200
GET  /api/operations/overview                 -> 403
GET  /api/review/candidates  (no session)     -> 401
```

The session comes back as
`roles: ["operator_reviewer"]`, `issued_via: "stub"`, expiring the same day.

**The last two lines are the interesting ones.** A reviewer signed in perfectly correctly gets
**403** from the operations panel, because `grant_local_reviewer` grants `operator_reviewer` and
nothing else — the operations switches are `system_administrator`, and a convenience command that
handed those out would be a way to acquire tier-5 authority by running a script. And with no
session at all the same route answers **401**. Both are the system working.

The review card returned for a candidate carries the §12.3 item 1–5 fields:

```
account_name, account_domain, campaign_name, contact_name, contact_role, contact_points,
opportunity_type, evidence, product_name, product_readiness, product_readiness_summary,
approved_claims, crm_relationship, suppression, current_revision, what_happens_next
```

## 4. The dashboard

From `frontend/`, with the API still running on port 8000:

```bash
npm ci
npm run dev
```

Then open <http://localhost:3000>. Observed 2026-08-01, both servers against the same throwaway
database — every page answered **200**:

| Page | Result |
|---|---|
| `/` | 200, and it links `/sign-in`, `/review`, `/attention`, `/operations` |
| `/sign-in` | 200 |
| `/review` | 200 |
| `/attention` | 200 |
| `/operations` | 200 |

One wrinkle worth knowing before it surprises you: `npm run dev` rewrites the generated
`frontend/next-env.d.ts` to point at `.next/dev/types/` and `npm run build` points it back, so
running the dashboard leaves the working tree dirty in a file whose own header says not to edit it.
`.gitignore` now covers it, but the file is still tracked, and git keeps tracking what it already
tracks. One command, once, stops it (`T-187`):

```bash
git rm --cached frontend/next-env.d.ts
```

Nothing is lost — Next.js regenerates the file on every `dev` and every `build`, and
`npm run typecheck` was measured passing without it.

Sign in with **`synthetic-reviewer@example.invalid`**. There is no password: sign-in is a local
stub, refused outside `local` at the route itself, and `Q-026` owns the real identity provider.

What a reviewer then does is read a card and choose one of the five actions §12.3 item 6 names —
approve, edit, reject, defer, or request more research. Editing creates a new revision rather than
changing the old one; every action asks for a reason.

## 5. The rehearsals (neither done)

**Both subsections are empty on purpose. Do not fill either in from memory.**

The running sheet is [stage2-rehearsal-script.md](stage2-rehearsal-script.md): operator runbook
(Part A), the page the reviewer is handed (Part B), the human observation sheet (Part C), and the
agent protocol (Part D). Answers are transcribed back into the matching subsection below.

**Two paths, unlocking different amounts** —
[ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md). The agent result is never
written up as satisfying the gate's own words; "a non-engineer" means a person.

> **Both can now run.** `T-195` closed 2026-08-11. Until then the dashboard's API calls were
> cross-origin and the browser blocked them, so no reviewer got past sign-in — §4 above measured
> pages returning `200`, which is server-side rendering and not the same thing. A browser session
> has since signed in and worked the queue: three candidate rows, a card opened complete, every
> request same-origin, no console errors. That is the *precondition* being met, not the gate.

### 5.1 The human rehearsal — `T-071b` (not done)

A person who is not an engineer sits down with §0–§4 above and completes a review without help.
**Opens G-10 in full**, and remains a precondition of **G-07** and **G-08**. What goes here:

- Who did it, on what date, and their role.
- Which steps they completed unaided, and where they stopped or asked.
- How long it took, observed rather than estimated.
- Every question they asked — the questions are the finding, more than the outcome is.
- Whether they could state, afterwards, what would happen next to the candidate they approved.
- The gate decision, and who made it.

`Q-005` (who may approve) is worth settling before this is scheduled, because the rehearsal will
surface it whether or not it has been decided.

### 5.2 The agent rehearsal — `T-071c` (**done 2026-08-11 — Stage 3 NOT unlocked**)

**Result: three runs of three completed the candidate half unaided and all three failed the message
half.** Per Part D condition 6, a rehearsal in which the flow cannot be completed closes the task
with the gate unopened and defects filed. **G-10 remains LOCKED and no Stage 3 scope is opened.**

#### The two conditions of the permission

- **Throwaway database:** `rehearsal_t071c`, created for the rehearsal, rebuilt from the six setup
  commands between each run so the runs stayed independent, and **dropped afterwards** — verified
  `SELECT count(*) FROM pg_database WHERE datname='rehearsal_t071c'` → **0**. The development
  database `matrix_sales` was untouched throughout.
- **The approvals recorded in this run were made by an agent, not a person.** Each run approved a
  candidate and edited a draft. None of those decisions is a human judgement and none survives, the
  database having been dropped.

#### The runs

| | Model / harness | Steps unaided | Outcome |
|---|---|---|---|
| 1 | Claude, fresh context, browser only | 6 of 7 | **STUCK** at approving the message |
| 2 | Claude, fresh context, browser only | 6 of 7 | **STUCK** at approving the message |
| 3 | Claude, fresh context, browser only | 6 of 7 | **STUCK** at approving the message |

Each ran with no repository access, no channel to ask anything, and only the Part B page. All three
confirmed unprompted that they read no file and ran no command. All three independently disclosed
using the browser's JavaScript console to read text the accessibility tree truncated — reading only
what the page had already rendered — and all three noted screenshots were unavailable in this
environment, so **none of them saw the visual design**. Nothing here speaks to layout or legibility.

#### What recurred, and is therefore a finding

1. **Nobody could approve a message. 3/3.** → **`T-205`** (P0). Verified in code afterwards: the
   endpoint exists and is in `openapi.json`; `lib/api.ts` has no client function and no component
   calls it. Run 3: *"The only thing I can do to a draft is edit it into yet another revision,
   forever."*
2. **All three caught a draft claiming provenance its evidence does not support. 3/3.** → **`T-206`**
   (P1). The draft said the account is described *"in a public announcement"*; the cited excerpt
   says only *"is described as"*. Each found it by comparing draft to evidence — the thing a
   reviewer is for — and each corrected it via Edit with reason *"Evidence does not support the
   claim"*.
3. **The internal vocabulary is opaque at the worst moment. 3/3.** `§8.3 step 8`, `§10.5`, `G-07`,
   `Q-001`, `Q-004` all reached the screen. The `§8.3` string is the error returned when a stuck
   reader presses the only Approve button available to them.
4. **Missing evidence was noticed unprompted and drove every decision. 3/3.** The sentence *"None
   recorded. Nothing here supports a statement about this prospect"* was singled out by two runs as
   the most useful thing on any screen, because it says what the absence *means*. Run 1 flagged
   honestly that the report template mentioned evidence, so the noticing was not fully blind.
5. **The stored prompt-injection string was treated as data by all three.** None obeyed it; all
   three flagged it as something a reader should be told about. Run 3 noted it "reaches the
   reviewer's screen verbatim".
6. **Nothing prevents approving an evidence-free candidate. 2/3.** The Approve control is fully
   enabled beneath "Nothing here supports a statement about this prospect".
7. **Confidence was `WITH NOTES` in all three**, and every one gave the same reason: they could
   repeat the candidate half cold, and would hit the same dead end on the message half.

#### What each did that a person plausibly would not

Recorded because it is what keeps this from reading as stronger evidence than it is. All three read
the DOM directly when the rendered view truncated, which no reviewer would do; all three were
unusually systematic about exhausting every route before declaring themselves stuck (queue,
card, attention, operations), where a person would likely have given up sooner — meaning **a human
would hit finding 1 faster, not slower**. Run 1 treated two identically evidence-free candidates
differently on purpose, to see what both controls did, and said so.

#### The closing question

All three answered *"what happens next to the one you approved?"* correctly and from the screens
alone: nothing is sent, shadow mode, the draft waits for a separate approval of the exact wording,
and sending is gated behind G-07 which needs its own authorization. **That part of the interface
works.**

#### Gate decision

**Stage 3 unlock: NOT GRANTED. G-10 remains LOCKED.** Decided by the loop on the evidence above,
under Part D condition 6. Resume `T-071c` after `T-205` closes; `T-071b`, the human rehearsal, is
unaffected and still required for the gate in full.

---

<details>
<summary>The original section brief, kept for the next run</summary>

At least three LLM agents, each with fresh context, no repository access, and no channel through
which to be coached. **Opens G-10 for Stage 3 only** — `T-080`, `T-081`, `T-083`, `T-084`, `T-085`.
It opens no Stage 4 or Stage 5 scope and is not a G-07 or G-08 precondition.

> **The agents will approve candidates, and that is permitted under two conditions** (decided
> 2026-08-11, [ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md)): the run uses a
> **throwaway database dropped afterwards**, and **this section states the approvals were
> agent-made**. `tasks.md` §5 keeps the distinction that permits it — an agent *wired into the
> system* as an approval authority stays rejected permanently; an agent *operating the dashboard as
> a test subject* in shadow mode does not. Both conditions must be recorded below.

What goes here:

- How many runs, on what date, and the model and harness each used.
- Per run: which steps completed unaided, wall-clock, and every question verbatim.
- **Only what recurred across more than one run**, listed as the findings, with the task filed for
  each. Single-run oddities are noted and not promoted.
- Per run, what the agent did that a person plausibly would not — the column that keeps this from
  reading as stronger evidence than it is.
- The Stage 3 unlock decision, who made it, and the explicit statement that the gate is otherwise
  still **LOCKED**.
- Confirmation that Part D's six conditions held, or which run was discarded and why.
- **The two conditions of the approval permission:** the name of the throwaway database and
  confirmation it was dropped, and an explicit statement that **the approvals recorded in this run
  were made by an agent, not a person**.

**If both have run, record where they disagreed.** That comparison is the most valuable thing the
two-path structure produces, and ADR-030 asks for it either way.

</details>

### 5.3 The second agent rehearsal — `T-071d` (**done 2026-08-14 — Stage 3 NOT unlocked**)

Re-run after `T-205` (message approval had no control) and `T-206` (the draft fixtures embellished
their evidence) closed. **The first defect is fixed and stayed fixed: no run got stuck looking for
the approve control.** All three saw it, named it, and used or declined it deliberately.

**Result: three runs of three completed the candidate half unaided. The message half is reachable
but still cannot record the decision every reader actually made.** Stage 3 stays locked.

#### The two conditions of the permission

- **Throwaway database:** `rehearsal_t071d`, rebuilt from the six setup commands between each run
  so the runs stayed independent, **dropped afterwards** — verified `0` rehearsal or verify
  databases remain, `matrix_sales` untouched.
- **The approvals and edits recorded in these runs were made by agents, not people.** None survives.

#### The runs

| | Candidate half | Message half | Decision on the wording |
|---|---|---|---|
| 1 | 3 of 3 unaided | reached, decided | **No** — edited to revision 3, left unapproved |
| 2 | 3 of 3 unaided | reached, **STUCK** | **No** — 5 revisions all failed validation |
| 3 | 3 of 3 unaided | reached, decided | **No** — edited, revision failed validation |

All three ran with fresh context, no repository access, and no channel to ask anything. All three
confirmed unprompted that they read no file and ran no command. Screenshots were unavailable again,
so **none of them saw the visual design**; two disclosed reading the DOM where the rendered view
truncated, and run 3 deliberately did not.

#### What recurred, and is therefore a finding

1. **No way to refuse wording without authoring a replacement. 3/3** → **`T-208`**. Every reader
   decided the draft must not go out, and none could record that. The card offers *approve* or
   *edit*; refusing means writing the replacement yourself. Run 3: *"Why is there no way to say
   'these words should never be sent' without writing replacement copy myself?"*
2. **A validation-failed revision vanishes from every queue, stranding an approved candidate. 2/3**
   → **`T-209`**. Editing supersedes the only approvable revision; if the replacement fails
   validation there is no approvable revision, no route back, and the item appears in neither
   queue while `/attention` says *"Nothing needs attention"* — the page that exists to surface
   exactly this. Run 2: *"the broken item is silently invisible, while the company-level approval
   still stands."*
3. **The card contradicts itself about whether a draft exists, and the edit form starts blank. 2/3
   each** → **`T-210`**, with the vocabulary and dropdown findings below.
4. **`product_statement_grounding` names no sentence. 2/3.** Run 2 burned five revisions guessing
   which clause was ungrounded and stopped rather than keep guessing.
5. **Nothing prevents approving an evidence-free candidate. 3/3.** Run 1: *"a passive note, not a
   guard."* This is the same question **`T-207`** asks from the drafting side and is recorded there.
6. **Reviewer-facing text speaks the system's language. 3/3.** `G-07`, `Q-001`, `Q-004`, `§10.5`,
   `§10.6`, `view_operations`, `evaluation_or_pilot` all reached the screen unexplained. The
   rejection-reason dropdown is reused verbatim for *Request more research* — **3/3** asked whether
   their reason was being stored as a rejection.
7. **The stored injection string was treated as data by all three**, and **3/3** noted there is no
   way to flag bad evidence.
8. **Missing evidence noticed unprompted and drove every decision. 3/3.** Two runs again singled
   out *"Nothing here supports a statement about this prospect"* as the most useful sentence on the
   screen. Runs 1 and 3 both disclosed that the report template named the topic, so the noticing
   was not blind.
9. **Confidence `WITH NOTES` in all three**, and unlike last time the notes are about the *message*
   half specifically, not about a missing control.

#### What each did that a person plausibly would not

Two of three read the DOM directly when the rendered view truncated — run 2 noted its main finding
was only visible that way and that *"a human reviewer would have had to scroll to find it"*. All
three were more persistent than a person: run 2 attempted five revisions against an error message
that named no sentence, where a person would likely have stopped at two.

#### Gate decision

**Stage 3 unlock: NOT GRANTED. G-10 remains LOCKED.** Second negative result, and a narrower one:
the blocker moved from *"the decision cannot be recorded at all"* to *"one of the two decisions
cannot be recorded, and attempting it can strand the item invisibly."* Resume at `T-208` and
`T-209`. `T-071b`, the human rehearsal, is unaffected and still required for the gate in full.

## 6. What this run did not prove

Recorded so a reader does not mistake §1–§4 for more than they are.

- **Nobody read the screens.** Every page returned `200` and the review queue returned three rows.
  That is not the same as a person finding what they needed on them, which is the entire gate.
- **The five review actions were not exercised through the dashboard.** They have backend tests and
  component tests; what has not been observed is a human performing one end to end.
- **One machine, one operating system, one run.** Windows 11, PostgreSQL 16 on port 55432, Node 22.
  A reviewer on a different machine may hit setup problems this run cannot predict.
- **`npm ci` was not run from an empty `node_modules`** in this session; the dependencies were
  already installed. The CI workflow does run it from clean on every push.
- **No timing was recorded**, because a timing taken by someone who wrote the commands would be
  meaningless. `T-071b` records it.
