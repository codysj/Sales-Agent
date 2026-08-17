"use client";

import { useState } from "react";

import { ApiRefused, approveRevision } from "../../lib/api";
import type { ApproveMessageResponse, CandidateDetail, ContactPointRow } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

/**
 * Approving the exact words, for an exact address (T-205; §12.3 item 6, §11.3, ADR-008).
 *
 * **Why this exists at all.** It is the second of the two approvals the architecture separates:
 * `ApproveForm` says this company is worth writing to, this one says *these words* may go to
 * *this address*. Until `T-205` only the first was built. The endpoint, the permission, the queue
 * entry and the generated type all existed; no component called it. Three rehearsal readers
 * (`T-071c`) each decided on the drafted message and then found nowhere to record the decision —
 * one wrote that "the only thing I can do to a draft is edit it into yet another revision,
 * forever."
 *
 * **It renders only for a revision that can actually be approved.** A superseded or invalidated
 * revision is shown with the reason instead of a button, because the backend refuses those with a
 * `409` and a form that submits into a guaranteed refusal teaches a reviewer that refusals are
 * normal. `T-071c` found the opposite failure — the *candidate* Approve button, pressed by a
 * reader with nothing else to try, answering with `§8.3 step 8 presents a candidate for review
 * before step 9 drafts for it`. Specification prose is not an error message.
 *
 * **The recipient is chosen, never defaulted** (ADR-008), matching `ApproveForm`. The two forms
 * deliberately look alike: they are the same act performed on different objects, and a reviewer
 * who has learned one should not have to learn the other.
 *
 * **What it does is stated before it is done, and what it did is stated after.** The backend's own
 * `what_happens_next` sentence is rendered rather than a local paraphrase — it is the one place
 * that knows whether shadow mode is on, and a copy here would drift the day it changes.
 */

type Outcome =
  | { kind: "idle" }
  | { kind: "approving" }
  | { kind: "approved"; response: ApproveMessageResponse }
  | { kind: "refused"; detail: string };

/** States a revision can be approved from. Anything else is shown its reason instead. */
const APPROVABLE_STATE = "review_pending";

function whyNotApprovable(state: string): string {
  if (state === "superseded") {
    return "This revision was superseded by a later edit, so it can no longer be approved. Reload the card to see the current wording.";
  }
  if (state === "invalidated") {
    // Deliberately not naming a cause. It used to say "the claims or product status it relied on
    // changed", which was the only way this happened until `T-208` made refusing wording the
    // other — and a reviewer who had just refused these words was then told a different reason
    // for their own decision. The attention page carries the reason; this only has the state.
    return "This revision was invalidated, so it cannot be approved. A new draft is needed.";
  }
  if (state === "approved") {
    return "These words have already been approved.";
  }
  return `This revision is ${state}, so it cannot be approved.`;
}

function describe(point: ContactPointRow): string {
  if (point.approvable) {
    return `${point.value} (${point.type}, ${point.verification_state})`;
  }
  return `${point.value} (${point.type}, ${point.verification_state} — cannot be approved until it is verified)`;
}

export function ApproveMessageForm({
  candidate,
  onChanged,
}: {
  candidate: CandidateDetail;
  onChanged?: (() => void) | undefined;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const revision = candidate.current_revision;
  if (revision === null) {
    return null;
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chosen === null || revision === null) {
      return;
    }
    const token = getSessionToken();
    if (token === null) {
      setOutcome({
        kind: "refused",
        detail: "You are not signed in, so nothing was approved. Sign in and try again.",
      });
      return;
    }

    setOutcome({ kind: "approving" });
    try {
      const response = await approveRevision(
        revision.revision_id,
        {
          recipient_contact_point_id: chosen,
          // Sent, not omitted: the backend refuses a revision that changed since it was read,
          // which is the whole guarantee that you approved the text you were shown.
          record_version: revision.record_version,
        },
        token,
      );
      setOutcome({ kind: "approved", response });
      onChanged?.();
    } catch (error) {
      setOutcome({
        kind: "refused",
        detail:
          error instanceof ApiRefused
            ? error.detail
            : `The approval could not be sent: ${String(error)}`,
      });
    }
  }

  if (outcome.kind !== "approved" && revision.state !== APPROVABLE_STATE) {
    return (
      <section aria-labelledby="approve-message">
        <h2 id="approve-message">Approve these words</h2>
        <p>{whyNotApprovable(revision.state)}</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="approve-message">
      <h2 id="approve-message">Approve these words</h2>
      <p>
        This approves the exact wording of revision {revision.revision_number} above, for the
        address you choose. It is a separate decision from approving the company. Nothing is sent:
        this build cannot send email at all, and switching that on is a separate decision nobody has
        taken (gate G-07).
      </p>

      {outcome.kind === "approved" ? (
        <div role="status">
          <p>
            Approved revision {revision.revision_number} for{" "}
            <strong>{outcome.response.recipient}</strong>.
          </p>
          <p>{outcome.response.what_happens_next}</p>
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          aria-label="Approve message"
        >
          <fieldset>
            <legend>Send these words to</legend>
            {candidate.contact_points.map((point) => (
              <div key={point.contact_point_id}>
                <input
                  type="radio"
                  id={`message-recipient-${point.contact_point_id}`}
                  name="message-recipient"
                  value={point.contact_point_id}
                  checked={chosen === point.contact_point_id}
                  disabled={!point.approvable}
                  onChange={() => {
                    setChosen(point.contact_point_id);
                  }}
                />
                <label htmlFor={`message-recipient-${point.contact_point_id}`}>
                  {describe(point)}
                </label>
              </div>
            ))}
          </fieldset>

          {candidate.contact_points.filter((point) => point.approvable).length === 0 && (
            <p role="alert">
              None of these addresses is verified, so this message cannot be approved yet.
            </p>
          )}

          <button
            type="submit"
            disabled={chosen === null || outcome.kind === "approving"}
            title={chosen === null ? "Choose the address these words would go to" : undefined}
          >
            {outcome.kind === "approving" ? "Approving…" : "Approve these words"}
          </button>
        </form>
      )}

      {outcome.kind === "refused" && <p role="alert">{outcome.detail}</p>}
    </section>
  );
}
