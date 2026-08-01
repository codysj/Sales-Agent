# Architecture decision records

Two kinds of ADR govern this repository.

**Inherited (ADR-001 … ADR-017)** live in
[the specification](../MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md) §16. They are **binding** and
are not restated here — the index below is a pointer, not a copy, so the two cannot drift. Changing
one requires a specification revision through an explicitly scoped task, not a local ADR.

**Local (ADR-018 …)** are implementation decisions this repository makes where the specification
leaves discretion. They live in this directory as `ADR-0NN-short-slug.md`.

> **Numbering rule:** local ADRs start at **ADR-018**. Never reuse or reassign a specification ADR
> number, and never renumber an existing local ADR. A superseded local ADR keeps its number and gains
> a `SUPERSEDED by ADR-0NN` status line.

## Inherited from specification v0.3 §16

| ADR | Status | Decision in one line |
|---|---|---|
| ADR-001 | DECIDED | The sales application owns workflow, scheduling, state, retries, approvals, and execution; OpenClaw is an optional planner/client. |
| ADR-002 | DECIDED | One repository and one modular backend, released together as an API process, a worker process, and a thin frontend. |
| ADR-003 | DECIDED | PostgreSQL stores authoritative workflow state and initially supplies the job queue, leases, and transactional outbox. |
| ADR-004 | DECIDED | Adopt HubSpot only if a commercial owner will use it; otherwise keep records internal during shadow mode and defer CRM integration. |
| ADR-005 | DECIDED | LinkedIn stays human-assisted — no unauthorized scraping and no autonomous account operation. |
| ADR-006 | DECIDED | The dashboard owns exact review and approval; a trusted channel-neutral gateway adds WhatsApp/iMessage as a complement. |
| ADR-007 | DECIDED | Schedules and verified events create application jobs that wake the worker; the agent is optional. |
| ADR-008 | DECIDED (shadow mode + initial live pilot) | Every initial recipient and exact message revision needs approval; every follow-up is approved too during the first live micro-pilot. |
| ADR-009 | DECIDED | At most one supervisor-style optional agent before any multi-agent work. |
| ADR-010 | DECIDED | PostgreSQL first; Redis or vector retrieval only after a measured requirement. |
| ADR-011 | DECIDED | Use OpenClaw inside a NemoClaw-managed OpenShell sandbox for the noncritical spike; pin, isolate, and regression-test the alpha runtime. |
| ADR-012 | DECIDED | Build both the sodium-battery and EV-charging configurations, but take only one through the first live pilot. |
| ADR-013 | DEFERRED | Establish a one-capable-model baseline and a labeled evaluation set before routing work to cheaper models. |
| ADR-014 | DECIDED | Lean-budget-first implementation; cost savings may never bypass evidence, security, approval, or product-claim controls. |
| ADR-015 | DECIDED | Candidate, message revision, approval, outreach thread, and background job each have independent states. |
| ADR-016 | DECIDED | Effectively-once external effects via immutable send command, transactional outbox, provider correlation, and reconciliation; ambiguous acceptance is `delivery_unknown`, never a blind retry. |
| ADR-017 | DECIDED (shadow baseline) | One capable commercial model behind a provider-neutral adapter; benchmark alternatives only after the baseline and labeled set exist. |

## Local to this repository

| ADR | Status | Decision |
|---|---|---|
| [ADR-018](ADR-018-toolchain-defaults.md) | ACCEPTED | Python 3.12 + uv + ruff + mypy(strict) + pytest, `backend/`/`frontend/` layout, no build backend. |
| [ADR-019](ADR-019-no-role-based-contact-matching.md) | ACCEPTED | Dedup matches on exact email or account+normalized name only; role-title matching and fuzzy scoring rejected. |
| [ADR-020](ADR-020-the-lifecycle-owner-brackets-a-step-it-does-not-perform.md) | ACCEPTED | `campaigns` brackets the research step with its own job types; `research_and_evidence` stays a lifecycle reader and is not added to the owner map. |
| [ADR-021](ADR-021-frontend-toolchain-defaults.md) | ACCEPTED (amended) | Frontend: npm + committed lockfile, Next.js 16 App Router, TypeScript 5.9 beyond `strict`, type-aware ESLint, Vitest; no styling until a screen needs it. Amended 2026-07-31: TS 5, not 6, because `openapi-typescript` requires it. |
| [ADR-022](ADR-022-requesting-more-research-adds-evidence-without-moving-the-candidate.md) | ACCEPTED | Requesting more research captures evidence for a candidate that stays in `review_pending`; adding a `review_pending → research_pending` edge to §8.2 rejected. |
| [ADR-023](ADR-023-an-approval-without-a-current-claim-set-is-refused.md) | ACCEPTED | The §11.3 transaction pins the product status version and claim set (§11.4); a campaign with no current claim set is refused rather than pinned null. |
| [ADR-024](ADR-024-approver-columns-reference-a-user-by-email.md) | ACCEPTED | Approver columns are foreign keys to `app_user.email` with RESTRICT, not to `app_user.id`: the row still says who without a join, and it matches what the application already writes. |
| [ADR-025](ADR-025-actor-columns-record-an-actor-not-a-user.md) | ACCEPTED | Columns recording who acted where the actor may be a service or the system stay strings holding an `Actor` id and take no foreign key; the approver columns of ADR-024 are the exception. |
| [ADR-026](ADR-026-who-acted-is-recorded-twice-and-the-rule-is-where-the-value-travels.md) | ACCEPTED | A human is a UUID in actor columns and an email in approver columns, deliberately: the actor id ends up in logs and §15.5 wants contacts redacted, while the approver is a business record a reviewer reads. |
| [ADR-027](ADR-027-where-a-development-process-may-register-the-fixture-source-adapter.md) | **PROPOSED** | Where a development process may register the Stage 1 fixture source adapter. Three options costed; (b) recommended. **Awaiting the user** — `T-172` stays `BLOCKED` until one is accepted. |

## Writing a local ADR

Keep it short. Record the decision, why, what was rejected, and what would make you revisit it — a
decision nobody can reverse later is worse than no record. Use the specification's status vocabulary
(§0.1): `ACCEPTED`, `PROPOSED`, `DEFERRED`, `REJECTED`, `SUPERSEDED`.

Where the specification and the implementation actually disagree, that is **not** an ADR — record it
in [reconciliation.md](../reconciliation.md) and file a scoped task.
