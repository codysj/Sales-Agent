# Backend module boundaries

Specification §18.2 names thirteen backend modules and calls their boundaries *internal contracts,
not separate services*. This document says which dependencies are allowed and why. The rules are
enforced by `backend/tests/test_module_boundaries.py`, which parses imports with `ast` — so a
violation fails the suite rather than surviving as a review comment.

There are no microservices here, and none are planned (ADR-002, §18.6).

## The modules

| Layer | Packages | Role |
|---|---|---|
| Foundation | `core`, `db` | Configuration, logging, middleware, engine, and the five lifecycle enums (`core/lifecycles.py`). Imports no domain module. |
| Platform | `audit_and_operations` | Audit trail, operational flags, version records. Every module may depend on it, because every consequential action needs an audit event (§3.5). |
| Mechanism | `jobs_and_outbox`, `model_gateway`, `messaging` | Generic machinery: leasing and delivery semantics, typed model tasks, channel transport. Deliberately ignorant of the domain. |
| Entities | `identity`, `products_and_claims`, `campaigns`, `prospects` | The nouns: who is acting, what may be claimed, which campaign, which prospect. |
| Workflow | `research_and_evidence`, `qualification`, `drafts_and_approvals`, `outreach_and_replies` | The verbs, in dependency order: gather evidence → qualify → draft and approve → execute and reconcile. |
| Adapter | `crm` | External sales-record synchronization, conditional on `Q-001` and gate **G-05**. |

Each package's `__init__.py` states what it owns and what it must not own, with specification
citations. Read that first; this file only covers the edges *between* them.

## Why these particular rules

Every rule is transcribed from the "must not own" column of specification §5.1, or from §6.3 — none
is an invented layering scheme.

**`core` and `db` import no domain module.** Foundation that knows about campaigns stops being
foundation, and the resulting cycle is discovered much later, at much greater cost.

> The five lifecycle enums in `core/lifecycles.py` are domain *vocabulary*, not domain *logic*:
> pure values and pure functions with no imports, so the dependency direction is unaffected.
> They sit together deliberately — ADR-015 requires the five lifecycles to stay independent, and
> that is easiest to audit when all five transition tables are visible on one screen. Each
> lifecycle's states are otherwise consumed only by the module that owns its entity.

**`model_gateway` imports no domain module.** §5.1: the LLM adapter must not own deterministic
eligibility, approval, suppression, or execution. Enforcing this as an import rule makes it
structural — the gateway *cannot* reach the rules it is forbidden to decide, so no future edit can
quietly hand it that authority.

> Note the distinction §5.1 draws. The *provider adapter* owns none of the deterministic controls.
> The **gateway** does enforce budgets and JSON-Schema validity before invoking any adapter — that is
> deterministic application logic that happens to live in the same package. This is an
> interpretation, not a divergence; see `docs/reconciliation.md`.

**`jobs_and_outbox` imports no domain module.** It moves work and guarantees effectively-once
delivery; it does not know what a candidate is. This holds for *schema* edges too, not only Python
imports: `outbox_event` carries no foreign key to `send_command`, because that table belongs to
`outreach_and_replies`. The shared `idempotency_key` — unique in both tables — is the join instead,
which costs nothing since §17.3 requires that key anyway (T-034). Domain modules register handlers and perform their
own §11.4 rechecks inside the dispatch transaction. Keeping the queue generic is what lets the
dispatch-time recheck live next to the rules it rechecks.

**`messaging` imports no domain module except `identity`.** ADR-006: the gateway is a complementary
overlay, never an approval authority and never a workflow dependency. It needs `identity` only to
map a channel identity onto an existing application user (§15.2). If it could import
`drafts_and_approvals`, "approve by WhatsApp" would be one import away.

**`crm` may import `prospects`, nothing else from the domain.** §5.1: the CRM adapter must not own
internal model runs, evidence, approvals, or job state. It needs accounts and contacts to satisfy
the §13.5 contract; it needs nothing else.

**Nothing imports `main` or `worker`.** The two process entry points wire everything else together
and must stay leaves. A module that imports one of them would drag a whole process's startup —
logging configuration, signal handlers, an engine — into a unit test.

**No cycles between packages.** Checked separately, because a set of individually legal edges can
still close a loop.

## Enforced rules

Generated from `FORBIDDEN` in `backend/tests/test_module_boundaries.py`. A test compares this block
against the checker and fails if the two drift, so this list cannot go stale.

<!-- BEGIN ENFORCED RULES -->
```text
core -/-> audit_and_operations, campaigns, crm, drafts_and_approvals, identity, jobs_and_outbox, messaging, model_gateway, outreach_and_replies, products_and_claims, prospects, qualification, research_and_evidence
crm -/-> campaigns, drafts_and_approvals, identity, jobs_and_outbox, model_gateway, outreach_and_replies, products_and_claims, qualification, research_and_evidence
db -/-> audit_and_operations, campaigns, crm, drafts_and_approvals, identity, jobs_and_outbox, messaging, model_gateway, outreach_and_replies, products_and_claims, prospects, qualification, research_and_evidence
jobs_and_outbox -/-> campaigns, crm, drafts_and_approvals, identity, messaging, model_gateway, outreach_and_replies, products_and_claims, prospects, qualification, research_and_evidence
messaging -/-> campaigns, crm, drafts_and_approvals, jobs_and_outbox, model_gateway, outreach_and_replies, products_and_claims, prospects, qualification, research_and_evidence
model_gateway -/-> campaigns, crm, drafts_and_approvals, identity, jobs_and_outbox, messaging, outreach_and_replies, products_and_claims, prospects, qualification, research_and_evidence
* -/-> main, worker
```
<!-- END ENFORCED RULES -->

`A -/-> B` means "A must not import B". A package not listed has no restriction beyond the two
global rules (`main` and cycles); the workflow modules are intentionally free to depend on entities
and on each other in dependency order.

## Changing a rule

A boundary rule encodes a specification prohibition. Loosening one is an architecture change, not a
refactor:

1. Confirm the specification actually permits it. If it does not, stop — file a reconciliation item
   in `docs/reconciliation.md` instead.
2. Change `FORBIDDEN` in the test and regenerate the block above.
3. Record the reasoning in a local ADR (`docs/adr/`, numbered from 018).

Adding a rule is ordinary work and needs only steps 2 and 3.
