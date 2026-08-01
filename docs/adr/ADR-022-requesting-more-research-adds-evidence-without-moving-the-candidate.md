# ADR-022 — Requesting more research adds evidence without moving the candidate

- **Status:** ACCEPTED (2026-07-31)
- **Scope:** Local to this repository. Does not modify any inherited specification ADR. Applies
  ADR-020's reasoning to a case ADR-020 did not cover; does not weaken it.
- **Specification basis:** §12.3 item 6 requires the review card to offer "request more research".
  §6.2 lists "request additional research" among OpenClaw's allowed responsibilities. §8.2 defines
  the campaign-candidate lifecycle as
  `imported → eligible/ineligible → research_pending → researched → review_pending →
  approved/rejected/deferred/invalidated` — with **no edge from `review_pending` back to
  `research_pending`**. ADR-015 keeps the five lifecycles independent; ADR-020 decides who performs
  a transition around a step its owner does not itself perform.
- **Found by:** `T-066`, while splitting the dashboard's decision actions.
- **Implemented by:** `T-153`.

## Context

The specification asks for an action it does not give a state for. Every other action on the review
card corresponds to an §8.2 edge: approve, reject, and defer all leave `review_pending` for a state
the lifecycle names. "Request more research" has no such edge, and the lifecycle offers no way back
into `research_pending` from review.

That is not obviously an oversight. Research already happened — the candidate reached
`review_pending` by way of `researched`, so a request for *more* research is a request for
additional evidence about a candidate that has already been researched once.

## Decision

**Requesting more research captures additional evidence for a candidate that stays in
`review_pending`. It is not a state transition, and it does not re-enter the research phase.**

Concretely:

| Piece | Owner | What it does |
|---|---|---|
| `CandidateDecision(kind=request_research)` | `campaigns` | Records who asked, why (§10.6 category), and any notes |
| `research.recapture_evidence` | `research_and_evidence` | Captures evidence for a candidate in `review_pending` |

`research.recapture_evidence` deliberately **enqueues nothing afterwards**. The existing
`research.capture_evidence` chains to `campaigns.complete_research` because that job's whole purpose
is the `research_pending → researched` transition. Here there is no transition to make: the
candidate is already `review_pending` and stays there, so the chain ends with the evidence.

`research_and_evidence` remains a **reader** of `CampaignCandidateState`. It is not added to
`LIFECYCLE_OWNERS`, and `test_a_reader_never_transitions_what_it_reads` is unchanged — which is the
point: this action transitions nothing, so the module that performs it needs no new authority.

**One pass at a time.** A second request while one is still in flight is refused rather than queued.
"In flight" counts jobs in `queued`, `leased`, or `retry` — not only `queued` — because a leased job
is precisely the one a reviewer would double-click on while waiting.

## Alternatives rejected

**Add a `review_pending → research_pending` edge.** The obvious fix, and the reason this ADR exists.
Three objections, in increasing order of seriousness:

1. It edits §8.2's lifecycle, which is inherited specification. Nothing in the specification asks
   for the edge; it would be improvised to make one action easier to implement.
2. It would take the candidate *out of review* while the reviewer believes it is still there. The
   review queue is filtered by state, so the card they were reading would vanish from the queue —
   and `T-063a`'s queue is what a reviewer works from.
3. It would then need `researched → review_pending` again to come back, and that edge does not exist
   either. Adding one edge means adding two, and the second one lets a candidate re-enter review
   without anybody deciding it should.

**Re-use `research.capture_evidence`.** It refuses any candidate outside `{eligible,
research_pending}`, and it chains to `campaigns.complete_research`, whose transition
`research_pending → researched` is invalid from `review_pending`. Relaxing its precondition to admit
`review_pending` would make the *first* research pass accept a state it should never see, in order
to serve the second — and the chained transition would then dead-letter. A separate job type keeps
each precondition describing exactly one situation.

**Record no reason.** §10.6 structures every other reviewer decision, and "why did somebody ask for
more research on this" is exactly the evaluation data §10.6 exists to collect — a campaign whose
candidates repeatedly need more evidence is telling you something about its research configuration.
Cheap to record now, impossible to reconstruct later.

## Consequences

- A reviewer can ask for more evidence without the candidate leaving their queue.
- The evidence appears on the card through `T-149`'s existing `current_evidence` read; nothing new
  is needed to surface it.
- `DecisionKind` gains a third value, so the decision table now records three of the four card
  actions. Approval stays in `campaigns.approval`, which is a different shape — it names a recipient
  and queues a draft.
- Nothing here decides what the *dashboard* does while a pass runs. Surfacing "a research pass is
  running" is a card concern and belongs with the button.
