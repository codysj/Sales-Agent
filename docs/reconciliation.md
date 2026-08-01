# Specification-versus-implementation reconciliation register

Where [the specification](MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md) and this repository
disagree, the divergence is recorded here and resolved through a scoped task. Neither side is
silently corrected: the specification is not edited to match the code, and the code is not changed to
match the specification, without a task that says so.

Per specification §23: *read the specification for intent and the versioned code and contracts for
exact implemented behavior; if they differ, report the mismatch and do not silently assume either is
correct.*

## Rules

- IDs are `R-###`, stable, never reused or renumbered — the same rule as task IDs.
- An entry is opened the moment a divergence is observed, even if the resolution is "no change".
- Every open entry names a resolution task ID, or explains why none is needed.
- This register records **divergences**. Decisions where the specification left discretion belong in
  [adr/](adr/) instead.
- Closing an entry requires evidence: the task that resolved it and what changed.

## Register

| ID | Opened | Spec section | Implemented behavior | Divergence | Resolution | Task | State |
|---|---|---|---|---|---|---|---|
| **R-001** | 2026-07-27 | §1.3 vs §19.6 | None yet — no dashboard code exists. | §1.3 marks "Review dashboard and authentication" as **GO now**, while §19.6 sequences the dashboard as Stage 2 after the Stage 1 exit gate. | Read §1.3 as scope authorization and §19.6 as sequencing. Enforced by gate **G-02**. No specification change proposed. Revisit only if the user directs dashboard-first work. | — (gate **G-02** in `tasks.md` §5) | **CLOSED** (2026-07-31, `T-058c`) — the tension resolved itself as designed: **G-02** opened on the Stage 1 exit evidence, so §19.6's sequencing is satisfied and §1.3's authorization now applies. Dashboard work (`T-060`) is `READY`. No specification change was needed, which is the outcome this entry predicted. |
| **R-002** | 2026-07-27 | §19.6 Stage 0 vs repository | None yet — no acceptance record is stored in the repository. | Stage 0's exit gate is stakeholder acceptance; the specification header already declares v0.3 approved for buildout, but no acceptance record exists in the repository. | Proceed with Stage 1 on the header's approved status; track the missing record as `T-009` (`BLOCKED`). Do not fabricate an acceptance record. | `T-009` | OPEN — blocked on stakeholder input |
| **R-003** | 2026-07-29 | §7.2 vs §8.2 | `Job.requires_human_review`, a boolean disposition on the `dead` state. `mark_for_human_review()` reaches `dead` with the flag set; `mark_dead()` leaves it false. | §7.2's job cycle ends in one of four outcomes — `SUCCEED \| RETRY \| DEAD-LETTER \| REQUIRE HUMAN REVIEW` — but §8.2's background-job lifecycle is `queued → leased → succeeded/retry/dead/cancelled`, with no state for review. Four outcomes, five states, no overlap for the fourth. | Treat §8.2 as authoritative for the **state machine** (ADR-015 requires the five lifecycles to stay independent, and adding a sixth job state to satisfy a different section is exactly the drift that rule exists to prevent) and §7.2 as authoritative for the **outcome set**. "Requires human review" is therefore a disposition on the terminal `dead` state, not a state: terminal and un-leasable like `dead`, but queryable separately so "we gave up" and "a person must decide" are never one queue. A DB check constraint pins the flag to `dead` only. No specification change proposed. Revisit if the dashboard (`T-069`) needs review-pending jobs to be resumable, which a terminal state cannot express. | `T-031` (done); revisit at `T-069` | **CLOSED** (2026-08-01, `T-180`) — the `T-069` revisit happened. The operations panel carries the disposition (`DeadJob.requires_human_review` in `operations_api.py`, rendered as "needs a human") and asks for **no resume action** — the only mutating operations route is the flag toggle — so the resumability a terminal state cannot express was never needed. The database constraint `NOT requires_human_review OR state = 'DEAD'` keeps the flag confined to the state it describes. `tests/test_job_retries.py::test_human_review_is_distinct_from_dead`. |
| **R-004** | 2026-07-30 | §9.5 vs `app/research_and_evidence/adapters/protocol.py` | `SourceAdapter.refresh(*, account_domain: str) -> Sequence[CapturedFact]`. `discover` and `import_records` exist and raise `SourceCapabilityUnavailable`. | §9.5 specifies `refresh(candidate_id) -> EvidenceSnapshot[]`. The implemented signature takes the account's normalized domain and returns `CapturedFact`, not ORM rows. | An adapter holds no database session, so resolving a candidate to something a source can be looked up by is the application's job; and an adapter that built `EvidenceSnapshot` rows would own persistence, provenance defaults, and the candidate association, which `capture.py` owns so that one place decides what a snapshot records. The §9.5 *capability set* is honoured in full — all three methods exist, and the two that are gated refuse loudly rather than returning an empty list. No specification change proposed. Revisit if a second adapter needs a different resolution key, which would mean the key belongs in a request object rather than a parameter. | `T-046` (done) | OPEN — benign, interpretation recorded |
| **R-005** | 2026-07-30 | §14.4 vs §8.2 | `invalidate_for_claim` moves `review_pending` and `approved` revisions to `invalidated`; a `draft` revision is left alone. | §14.4 says a new claim version "triggers an invalidation job for dependent pending **drafts** and approvals", but §8.2's revision lifecycle has no `draft → invalidated` edge — `draft` goes only to `validation_failed`, `review_pending`, or `superseded` (`T-010`). | Treat §8.2 as authoritative for the state machine (ADR-015: widening a lifecycle table to satisfy a different section is the drift that rule exists to prevent) and satisfy §14.4's *intent* by a different mechanism: a draft citing a withdrawn claim cannot pass `T-055`'s validation, so it can never reach a reviewer. The safety outcome is identical; only the state label differs. No specification change proposed. Revisit if the dashboard (`T-064`) needs to show operators a draft that was killed before validation, which the current states cannot express. | `T-056` (done); revisit at `T-064` | **CLOSED** (2026-08-01, `T-180`) — the `T-064` revisit happened. Leaving a `draft` alone is **forced, not chosen**: `ALLOWED_TRANSITIONS[MessageRevisionState.DRAFT]` is `{validation_failed, review_pending, superseded}` (§8.2), so `draft → invalidated` does not exist and nothing is "killed before validation" for the review card to show. It is also safe — a draft citing a withdrawn claim fails closed on the way to review, via `_check_claim_currency` (§10.5). `tests/test_invalidation.py::test_a_draft_revision_is_left_alone` and `tests/test_revision_validation.py` (`Check.CLAIM_CURRENCY`). |

## Not divergences

Recorded so they are not re-opened as findings:

- **Only `fake` exists in `ModelProvider`.** §18.4 names Claude Sonnet 5 as a *candidate* subject to
  approval. A single-member enum is staged implementation behind gate **G-03** and `Q-012`, not a
  contradiction. See `T-050`.
- **Budget enforcement lives in `model_gateway`.** §5.1 says the LLM *adapter* must not own budgets;
  `T-050` puts budget enforcement in the **gateway**, which is deterministic application logic that
  runs before any provider adapter is invoked. The adapter itself owns none of it. Interpretation,
  not divergence — see `docs/architecture/modules.md`.
- **No CRM adapter.** §13.2 makes HubSpot conditional on `Q-001`. Absence is the specified behavior.
- **No messaging gateway, no OpenClaw client.** §1.3 places both after the Stage 1 vertical slice and
  marks them noncritical.
- **The specification lives at `docs/…v0.3.md`, not `docs/spec/`.** A repository layout choice made in
  `T-001`, not a behavioral divergence.
