# Stage 1 exit evidence

- **Recorded:** 2026-07-31
- **Task:** `T-058c` (closing `T-058`)
- **Gate:** **G-02** — specification §19.6, Stage 1: *"Full import-to-draft flow works with no
  external writes."*
- **Verdict:** the exit condition is met. Every command and number below was observed on the date
  above; nothing here is reconstructed or estimated.

## What the gate asks, and where each half is answered

| §19.6 requirement | Answered by |
|---|---|
| Full import-to-draft flow works | [The pipeline, end to end](#1-the-pipeline-end-to-end) |
| …with no external writes | [The zero-external-write proof](#3-the-zero-external-write-proof) |
| …on synthetic fixtures | [Synthetic-only](#4-synthetic-only) |
| …on a deterministic fake model and a fake external-effect adapter | [The two fakes](#5-the-two-fakes) |

## 0. Canonical checks

Run from `backend/` on 2026-07-31, in the order `process.md` §5 gives them.

```
$ uv run ruff check .
All checks passed!

$ uv run ruff format --check .
168 files already formatted

$ uv run mypy app
Success: no issues found in 95 source files

$ uv run pytest -q
1664 passed in 153.46s (0:02:33)

$ uv run alembic check
No new upgrade operations detected.
```

`ruff format --check` failed twice while this record was being assembled, and both are recorded
because both were real. First on `tests/test_jobs.py`, left unformatted by `T-148`'s final edit;
then on `tests/test_shadow_slice.py`, after the temporary probe used to gather the counts in §1
was removed. Each was formatted and the check re-run. The output above is the final run, taken
after both fixes, and `pytest -q` was re-run after each.

## 1. The pipeline, end to end

`backend/tests/test_shadow_slice.py` (**34 passed**) drives §24 item 5 — *import candidate, create
campaign membership, apply eligibility, store evidence, qualify and classify, draft from approved
claims, show review, stop before external send* — from an empty migrated database.

It runs **entirely through the worker**. The test enqueues membership jobs and drains the queue;
`runner.execute` does everything else. Two tests hold that structurally: one parses `run_slice`'s
AST for calls to the six pipeline entry points the earlier direct composition used, and one
asserts the module never imports them at all — it cannot call what it never imported.

Counts observed from one slice run:

| Entity | Count |
|---|---|
| Product | 2 |
| Campaign | 2 |
| ImportBatch | 1 |
| Account | 12 |
| Contact | 13 |
| ContactPoint | 13 |
| CampaignCandidate | 15 |
| EvidenceSnapshot | 4 |
| ModelRun | 10 |
| QualificationRun | 5 |
| MessageDraft | 5 |
| MessageRevision | 5 |
| Job | 64 |

Terminal states:

```
CampaignCandidate: approved:5, ineligible:10
MessageRevision:   review_pending:5
```

**Ten of fifteen candidates were refused**, which is the point of the `T-041` corpus: it is mostly
refusal cases (non-US geography, unverified or missing addresses, phone-only contacts). A slice
that advanced all fifteen would be a slice whose eligibility gate did nothing.

Jobs, by type and outcome — every one succeeded, none died, none was left queued:

```
campaigns.create_membership     succeeded: 17
qualification.apply_eligibility succeeded: 17
campaigns.start_research        succeeded:  5
research.capture_evidence       succeeded:  5
campaigns.complete_research     succeeded:  5
qualification.qualify_candidate succeeded:  5
drafts.draft_message            succeeded:  5
drafts.validate_revision        succeeded:  5
```

## 2. The pipeline stops for a human, and the stop is asserted

The worker ran in **two waves: 54 jobs, then 10**. Everything before the gap is automatic;
nothing after it runs until a person approves.

§8.3 step 9 creates a draft *on candidate approval*. So the automatic cascade ends at
`review_pending` and enqueues nothing, and `drafts.draft_message` **refuses any candidate that is
not `approved`** — a precondition on the handler, not a convention about who enqueues, because a
stray enqueue or a replayed payload would otherwise produce a draft nobody approved.

Both halves are tested: no drafting job exists *in any state* before the approval, and a drafting
job for a candidate in any of the five other states dead-letters without writing a revision.

## 3. The zero-external-write proof

**A socket guard, not an HTTP-client mock.** `backend/tests/netguard.py` patches
`socket.socket.connect`, `connect_ex`, and `socket.create_connection`, refusing every address but
the test database. Patching at the socket means the guarantee also covers `smtplib`, a raw socket,
and any provider SDK that vendors its own transport — a guard that knew about `httpx` would say
nothing about those. The whole slice runs under it, and three control tests prove the guard itself
fails when a connection is attempted, so it cannot be silently inert.

**Nothing was queued for sending.** After the full run:

```
Approval=0  SendCommand=0  SendAttempt=0  OutboxEvent=0
```

`Approval` is zero because *message* approval is Stage 2's; the five candidate approvals in this
run are candidate-lifecycle transitions, which is a different decision (§8.2 has both,
deliberately). §8.3 step 12's send waits on the message approval this stage never gives.

## 4. Synthetic only

Every prospect, account, product, claim, and model output in this run comes from
`backend/app/fixtures/`. Names carry a `SYNTHETIC-` prefix and domains are IANA reserved example
domains (`*.example.com`, `*.example.org`, `*.example.net`). No real prospect, contact, company, or
customer record is involved, and `app/fixtures/` is imported by no production module — a code path
that needed a fixture to work is a code path that would break on real data.

Fixture claims say what they are: *"Placeholder wording, approved by nobody, never for a real
recipient."* No product readiness in the fixture set is `sellable_now`.

## 5. The two fakes

**The model.** `FakeModelAdapter` is a lookup keyed by the SHA-256 of the rendered prompt, not a
generator: an unmatched prompt raises rather than returning something plausible. All ten
`ModelRun` rows in this run recorded provider `fake` and model `deterministic-fake`.
`build_provider` remains the only way to obtain an adapter, gate **G-03** is locked, and
`REAL_PROVIDER_ADAPTERS` is empty and asserted empty.

**The external-effect adapter.** `T-035a`'s fake records calls and can simulate success, timeout,
ambiguous acceptance, and rate limiting. Nothing in this run reached it, which is the correct
outcome for Stage 1: there was no approved message to dispatch.

## 6. What this evidence does *not* claim

Stated plainly, because a gate record that overstates is worse than none:

- **It says nothing about a real model's behaviour.** No real provider runs here (**G-03**). The
  injection corpus proves *placement and containment* — a hostile payload cannot reach the
  instruction region of a prompt, and no deterministic code path reads evidence text — not that a
  real model would ignore an instruction it was told to treat as data. `T-083` owns that.
- **It says nothing about deliverability, provider behaviour, or DNS.** Those are Stage 5 and
  gate **G-07**.
- **No stakeholder has accepted anything.** `T-009` is still open; `R-002` records that the Stage 0
  acceptance record does not exist in this repository and was not fabricated.
- **Quality is unmeasured.** The labeled evaluation set is Stage 3. This gate is about the flow
  working and writing nothing outward, not about whether the drafts are any good.

## 7. Reproducing this

From `backend/`, with PostgreSQL running (`docker compose up -d db`):

```bash
uv run pytest -q tests/test_shadow_slice.py
```

The slice is deterministic — a test runs it twice and asserts the same shape both times — so a
reviewer who gets different counts has found a real change, not noise.
