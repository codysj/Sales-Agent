# ADR-020 — The lifecycle owner brackets a workflow step it does not itself perform

- **Status:** ACCEPTED (2026-07-31)
- **Scope:** Local to this repository. Does not modify any inherited specification ADR. Refines how
  ADR-015 is applied; does not weaken it.
- **Specification basis:** §8.2 defines the campaign-candidate lifecycle including
  `research_pending` and `researched`; §8.3 steps 5–6 assign the research work itself to
  `research_and_evidence`; §7.2 requires state, audit, and the next job to commit atomically;
  ADR-015 keeps the five lifecycles independent and forbids one module transitioning another's
  entity. None of them says who moves a candidate through a step performed by a module that does
  not own its lifecycle. This ADR fills exactly that gap.
- **Implemented by:** `T-147` (`backend/app/campaigns/jobs.py`).

## Decision

**`campaigns` owns every campaign-candidate transition it has not already delegated, including the
two around research, and it performs them in job types of its own that bracket the research step.**

The chain is:

| Job type | Owner | Transition |
|---|---|---|
| `qualification.apply_eligibility` | `qualification` | `imported → eligible` / `ineligible` |
| `campaigns.start_research` | `campaigns` | `eligible → research_pending` |
| `research.capture_evidence` | `research_and_evidence` | none — it stores evidence |
| `campaigns.complete_research` | `campaigns` | `research_pending → researched` |

`research_and_evidence` stays a **reader** of `CampaignCandidateState` in `LIFECYCLE_READERS`. It is
not added to `LIFECYCLE_OWNERS`, and `test_a_reader_never_transitions_what_it_reads` is unchanged.

## Why

The distinction that decides this is **whether the transition is the step's outcome or bookkeeping
about it.**

`qualification` is a candidate-lifecycle owner, and that was right: §8.3 step 4 makes hard
eligibility *the thing that moves* a candidate out of `imported`. The decision and the transition
are the same event, and splitting them would put a candidate in a state nobody had decided.

Research is not like that. Its outcome is an `EvidenceSnapshot` — provenance, retrieval time,
retention class. That a candidate is now "researched" is a statement about its position in the
workflow, not about what was found; a candidate with zero evidence is researched too (GP-02:
missing facts remain missing). Bookkeeping about workflow position belongs to the module that owns
the workflow state machine.

Bracketing also buys something the alternatives do not. `start_research` commits
`eligible → research_pending` **and** the capture job in one transaction (§7.2), so a crash during
capture leaves a candidate visibly *in* research rather than one that looks untouched — the
difference between "retry this" and "nobody knows".

## What was rejected

**Adding `research_and_evidence` to `LIFECYCLE_OWNERS` with a compensating test.** This is the
`qualification` precedent and it is the tempting one: one line, no new job types. Rejected because
the precedent does not transfer — see above — and because each module that performs a §8.3 step is
a candidate for the same argument. Granted to all of them, the owner map lists most of the backend
and ADR-015's guarantee is gone. The rule survives by the exceptions being principled, not by them
being few.

**A `campaigns`-owned helper (`mark_researched(...)`) that `research_and_evidence` calls.** Rejected
as evasion. `test_a_reader_never_transitions_what_it_reads` detects the import of `transition` by
name, so a differently-named wrapper would pass the test while doing the forbidden thing — the same
reasoning that rejected aliasing `revisions.transition` in `T-055`. A test that a rename defeats is
not a guarantee.

**Letting the capture job transition and relaxing the invariant test.** Rejected outright: the test
found this defect, and editing the detector because it detected something is how a safety invariant
becomes decoration.

## Cost, stated plainly

Two extra job types and two extra links in the chain for one candidate's research. A reader tracing
the pipeline sees four jobs where three would do. That is the price of the lifecycle owner staying
the only writer, and it is the cheaper side of the trade.

## Revisit if

- A third module needs the same bracketing, at which point the pattern deserves a named abstraction
  rather than a third hand-written pair.
- §8.2 gains a state whose transition genuinely *is* another module's outcome, in which case that
  module joins `LIFECYCLE_OWNERS` on the `qualification` argument, not this one.
- The chain's length becomes a measured problem — latency, not aesthetics.
