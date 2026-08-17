import type { CandidateDetail } from "../../lib/api";

/**
 * Whether a candidate-level decision can still be taken (T-211; §8.2, ADR-022).
 *
 * Two components need this and they must agree, so it lives here rather than twice. The backend's
 * `DECIDABLE_STATE` is the authority — approving, rejecting, deferring, and asking for more
 * research all require `review_pending` — and a form offered outside it submits into a refusal
 * the client could have predicted.
 *
 * That is not a hypothetical: `T-071c` watched a reader press the candidate Approve button on a
 * candidate that was past it and receive *"§8.3 step 8 presents a candidate for review before
 * step 9 drafts for it"*. `T-211` found the same shape again through `T-208`'s refusal flow —
 * every candidate with a draft is `approved`, so *every* card showing a draft was offering three
 * controls that could only fail.
 */
export const DECIDABLE_STATE = "review_pending";

/** What to say instead of the form, in terms of the decision that was already taken. */
export function whyNotDecidable(state: CandidateDetail["state"]): string {
  if (state === "approved") {
    return (
      "This candidate has already been approved for outreach, so there is no candidate decision " +
      "left to take. The message itself is still yours to approve, refuse, or edit."
    );
  }
  if (state === "rejected") {
    return "This candidate was rejected. Nothing further happens to it.";
  }
  if (state === "deferred") {
    return "This candidate is deferred. It returns to the review queue on the date or event it was deferred until.";
  }
  if (state === "invalidated") {
    return "This candidate was invalidated — something it depended on changed — so no decision can be recorded against it.";
  }
  return `This candidate is ${state}, so it is not waiting on a decision.`;
}
