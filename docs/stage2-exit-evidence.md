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

> **Neither can run yet.** `T-195`: the dashboard's API calls are cross-origin and the browser
> blocks them, so no reviewer gets past sign-in. §4 above measured pages returning `200`, which is
> server-side rendering and not the same thing.

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

### 5.2 The agent rehearsal — `T-071c` (not done)

At least three LLM agents, each with fresh context, no repository access, and no channel through
which to be coached. **Opens G-10 for Stage 3 only** — `T-080`, `T-081`, `T-083`, `T-084`, `T-085`.
It opens no Stage 4 or Stage 5 scope and is not a G-07 or G-08 precondition. What goes here:

- How many runs, on what date, and the model and harness each used.
- Per run: which steps completed unaided, wall-clock, and every question verbatim.
- **Only what recurred across more than one run**, listed as the findings, with the task filed for
  each. Single-run oddities are noted and not promoted.
- Per run, what the agent did that a person plausibly would not — the column that keeps this from
  reading as stronger evidence than it is.
- The Stage 3 unlock decision, who made it, and the explicit statement that the gate is otherwise
  still **LOCKED**.
- Confirmation that Part D's six conditions held, or which run was discarded and why.

**If both have run, record where they disagreed.** That comparison is the most valuable thing the
two-path structure produces, and ADR-030 asks for it either way.

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
