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
| **R-001** | 2026-07-27 | §1.3 vs §19.6 | None yet — no dashboard code exists. | §1.3 marks "Review dashboard and authentication" as **GO now**, while §19.6 sequences the dashboard as Stage 2 after the Stage 1 exit gate. | Read §1.3 as scope authorization and §19.6 as sequencing. Enforced by gate **G-02**. No specification change proposed. Revisit only if the user directs dashboard-first work. | — (gate **G-02** in `tasks.md` §5) | OPEN — benign |
| **R-002** | 2026-07-27 | §19.6 Stage 0 vs repository | None yet — no acceptance record is stored in the repository. | Stage 0's exit gate is stakeholder acceptance; the specification header already declares v0.3 approved for buildout, but no acceptance record exists in the repository. | Proceed with Stage 1 on the header's approved status; track the missing record as `T-009` (`BLOCKED`). Do not fabricate an acceptance record. | `T-009` | OPEN — blocked on stakeholder input |
| **R-003** | 2026-07-29 | §7.2 vs §8.2 | `Job.requires_human_review`, a boolean disposition on the `dead` state. `mark_for_human_review()` reaches `dead` with the flag set; `mark_dead()` leaves it false. | §7.2's job cycle ends in one of four outcomes — `SUCCEED \| RETRY \| DEAD-LETTER \| REQUIRE HUMAN REVIEW` — but §8.2's background-job lifecycle is `queued → leased → succeeded/retry/dead/cancelled`, with no state for review. Four outcomes, five states, no overlap for the fourth. | Treat §8.2 as authoritative for the **state machine** (ADR-015 requires the five lifecycles to stay independent, and adding a sixth job state to satisfy a different section is exactly the drift that rule exists to prevent) and §7.2 as authoritative for the **outcome set**. "Requires human review" is therefore a disposition on the terminal `dead` state, not a state: terminal and un-leasable like `dead`, but queryable separately so "we gave up" and "a person must decide" are never one queue. A DB check constraint pins the flag to `dead` only. No specification change proposed. Revisit if the dashboard (`T-069`) needs review-pending jobs to be resumable, which a terminal state cannot express. | `T-031` (done); revisit at `T-069` | OPEN — benign, interpretation recorded |

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
