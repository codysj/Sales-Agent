# ADR-030 — The G-10 rehearsal has two evidence paths, and they unlock different amounts

**Status:** ACCEPTED (2026-08-11, `T-071c`) — the two-path structure was directed by the user in
session; the loop wrote the boundary between the paths and would not have accepted a single-path
reading for itself.
**Spec:** §19.6 Stage 2 exit gate, §3.5, §12.3

## The problem

**G-10** reads: *a non-engineer completes reviews without understanding the agent stack.* It is the
Stage 2 exit gate and the entry gate for Stage 3, and with `T-071a` closed it is the only thing
between this repository and every stage after it.

It has been locked since Stage 2 finished because it needs something the development loop cannot
supply: a person, an hour, and no explanation. `T-071b` has therefore sat `BLOCKED` on scheduling,
while work that depends on it has not been startable.

The question put to the loop was whether a sufficiently careful pass by a team of LLM agents could
satisfy the gate instead.

## What an agent team can actually establish

More than is comfortable to dismiss, and in one respect more than a single human session does.

Given genuinely fresh context, no access to this repository, and only the reviewer-facing page from
the running sheet, an agent driving a real browser tests:

- Whether the documented setup path works when followed literally from cold.
- Whether the screens are navigable and legible without knowing the architecture.
- Where comprehension breaks — and across **several independent runs**, which is a stronger
  interface signal than one session produces. A defect three of four independent readers hit is a
  defect; one person hitting it is an anecdote.
- Whether the closing question — *what happens next to the one you approved?* — is answerable from
  the screens alone.

These are real properties of the interface, and they are the properties `T-071a` explicitly could
not measure: it recorded that every page answered `200`, and recorded plainly that nobody had read
them.

## What it cannot establish, and no prompt fixes

- **It is not a person.** The gate does not exist to test a reader. It exists to establish that the
  humans who will eventually approve real messages to real recipients are able to. An agent's
  fluency with unfamiliar software is unrepresentative in the *optimistic* direction — it will not
  skim, will not misread a label, will not give up, and does not arrive with the impatience of
  someone doing this between two other tasks.
- **It carries no accountability.** §3.5 and §6.3 make approval a human act, structurally. Evidence
  that an agent completed the flow is evidence about the screens; it is not evidence that the
  approval authority the safety model depends on is workable in practice.
- **It shares an ancestry with the thing it is grading.** The screens, the fixture set, and the
  reviewer-facing page were all written with model assistance. An agent finding them clear is a
  weaker signal than an unrelated human finding them clear, and the correlation cannot be removed
  by instruction.

## Decision

**G-10 has two evidence paths, and they unlock different amounts.**

| Path | Task | Evidence | Unlocks |
|---|---|---|---|
| Agent-team rehearsal | `T-071c` | ≥3 independent agent runs, fresh context each, transcripts recorded verbatim | **G-10 for Stage 3 only** — `T-080`, `T-081`, `T-083`, `T-084`, `T-085` |
| Human rehearsal | `T-071b` | One non-engineer, observed, timings taken | **G-10 in full** — Stage 4 and Stage 5 scope, and the G-07/G-08 precondition |

Both record into `docs/stage2-exit-evidence.md` §5, in separately labelled subsections. Neither
overwrites the other, and the agent result is never described as satisfying the gate's own words.

**The gate's text is not reinterpreted.** "A non-engineer" continues to mean a person. What this
record does is state what *partial* evidence buys, rather than leaving the gate binary and therefore
leaving Stage 3 hostage to calendar availability.

### Why the line falls between Stage 3 and Stage 4

Stage 3 is internal measurement of a synthetic system: evaluation fixtures, a correctness suite, an
adversarial safety suite, a recovery suite, cost reporting. Every output is a test artifact. If the
interface evidence underneath it proves optimistic, the cost is rework on a harness, and the harness
was going to be re-run against the real configuration at `T-111` regardless.

Stage 4 adds interfaces other people touch. Stage 5 adds a mailbox. From there the question stops
being *is this screen clear* and becomes *can the person who bears responsibility for a message
going to a real recipient actually operate the thing that sends it* — which is a safety property,
and an agent cannot stand in for it.

## What the agent path must satisfy to count

Stated here because a rehearsal that fails these is a system grading its own homework, and the
result would look identical to a real one.

1. **No repository access.** An agent that has read this codebase is disqualified for that run.
   Its only inputs are the reviewer-facing page and the running browser.
2. **Fresh context per run.** No agent may see another's transcript, findings, or conclusion.
3. **At least three independent runs.** One run is an anecdote; the finding is what recurs.
4. **Verbatim transcripts.** Every question and every wrong turn recorded as produced, including
   the ones that look trivial. Filtering is where this kind of evidence usually dies.
5. **No coaching, enforced by construction** rather than by discipline — the operator cannot answer
   an agent mid-run, because there is no channel through which to do it.
6. **A negative result is a result.** An agent that cannot complete the flow closes the task with
   the gate still locked and a filed defect, exactly as a human failure would.

## Rejected

- **Redefine "non-engineer" to include an LLM agent.** The cheapest option and the one that
  destroys the evidence. It would put a sentence in the exit-evidence document asserting the gate's
  own words were met by something that is not what those words mean — in a repository whose entire
  documentary discipline is that recorded evidence says exactly what was observed and no more. The
  §5 section of the exit evidence opens with *"Do not fill it in from memory"* for the same reason.
- **Keep the gate binary and wait for a human.** Defensible, and it was the status quo. Rejected
  because it makes Stage 3 hostage to one hour of someone's calendar while a genuinely informative
  test is available immediately — and because the agent pass will surface interface defects that
  are better fixed *before* a person is asked to sit down, which makes the human session worth more
  when it happens.
- **Run the agent pass and treat it as a dress rehearsal with no unlock value.** Nearly right, and
  rejected only because it is untrue to what the evidence establishes. Multi-run agent evidence
  about whether an interface is self-explanatory is real evidence; recording it as worthless would
  be as inaccurate as recording it as sufficient.

## Revisit when

- The human rehearsal happens and **disagrees materially** with the agent runs. That comparison is
  the most valuable thing this two-path structure produces, and it is worth recording explicitly in
  §5 either way: if agents and a person diverge, the gap itself tells you what agent evidence is
  worth in this repository, and this record should be amended with that finding.
- Anything reaches Stage 4. At that point the human path is required and this record's split has
  done its job.
