"use client";

import { useState } from "react";

import { ApiRefused, approveCandidate } from "../../lib/api";
import type { ApproveResponse, CandidateDetail, ContactPointRow } from "../../lib/api";
import { getSessionToken } from "../../lib/session";
import { DECIDABLE_STATE, whyNotDecidable } from "./decidable";

/**
 * Approving a candidate for an exact recipient (T-154b; §12.3 items 1 and 6, ADR-008).
 *
 * **The recipient is chosen, never defaulted.** ADR-008 approves an exact recipient and an exact
 * revision together; an address the form pre-selected is an address the system chose and the
 * approver ratified without deciding. So the radio group starts with nothing selected and the
 * button stays disabled until one is picked — and `T-154a`'s endpoint requires the field anyway,
 * which is the guard that actually binds.
 *
 * **Unverified addresses are listed and disabled, not filtered out.** A reviewer who cannot see
 * the mailbox they expected has no way to tell "this address is unusable" from "the system has
 * never heard of it", and those need different actions — one is a data problem to fix, the other
 * is a research gap. Each disabled option says which it is.
 *
 * **What approval does is stated before it is done.** It queues drafting; it sends nothing. Gate
 * **G-07** governs live sending, and a reviewer pressing a button labelled "Approve" deserves to
 * know which of those they are causing.
 *
 * **And it is the same noun the card's footer uses (`T-215`).** This paragraph said "queues a
 * draft" while the footer said approving "creates no outbound message", one section below. Both
 * were true. Read together they are a contradiction, because two nouns for what a reader takes to
 * be one object leaves them guessing which is which — so the sentence now says what a draft is
 * rather than trusting the word to carry it.
 *
 * **The result names the address.** An approval confirmed as "done" is one nobody can check; an
 * approval confirmed as "approved for `someone@example.com`" is one a reviewer can catch
 * themselves having got wrong.
 */

type Outcome =
  | { kind: "idle" }
  | { kind: "approving" }
  | { kind: "approved"; response: ApproveResponse }
  | { kind: "refused"; detail: string };

function describe(point: ContactPointRow): string {
  if (point.approvable) {
    return `${point.value} (${point.type}, ${point.verification_state})`;
  }
  return `${point.value} (${point.type}, ${point.verification_state} — cannot be approved until it is verified)`;
}

export function ApproveForm({
  candidate,
  onChanged,
}: {
  candidate: CandidateDetail;
  onChanged?: (() => void) | undefined;
}) {
  const [chosen, setChosen] = useState<string | null>(null);
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const approvable = candidate.contact_points.filter((point) => point.approvable);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (chosen === null) {
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
      const response = await approveCandidate(
        candidate.candidate_id,
        {
          recipient_contact_point_id: chosen,
          record_version: candidate.record_version,
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

  // A candidate decision has already been taken, so the server would refuse this and the client
  // can see that without asking (`T-211`, criterion 2). §8.2 offers the candidate lifecycle one
  // edge out of `approved` — to `invalidated` — and none at all out of `rejected`; the backend's
  // `DECIDABLE_STATE` says the same thing. Offering the form anyway is how `T-071c` watched a
  // reader press a button and receive specification prose.
  if (outcome.kind !== "approved" && candidate.state !== DECIDABLE_STATE) {
    return (
      <section aria-labelledby="approve">
        <h2 id="approve">Approve for outreach</h2>
        <p>{whyNotDecidable(candidate.state)}</p>
      </section>
    );
  }

  return (
    <section aria-labelledby="approve">
      <h2 id="approve">Approve for outreach</h2>
      <p>
        Approving queues a draft for the address you choose. Nothing is sent: a draft is written
        here for you to read and approve, and is delivered to nobody. This build cannot send email
        at all, and switching that on is a separate decision nobody has taken (gate G-07).
      </p>

      {/* Once it is approved the form is gone, not merely accompanied by a success message
          (`T-210`). Leaving it on screen offers a second approval that the server would refuse,
          and puts a live control next to the sentence saying the decision is already taken —
          which is the same "the card does not reflect what just happened" this task is about. */}
      {outcome.kind === "approved" ? null : candidate.contact_points.length === 0 ? (
        <p>
          No contact points are recorded for this contact, so there is no address to approve. This
          candidate needs a verified address before it can be approved.
        </p>
      ) : (
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          aria-label="Approve candidate"
        >
          <fieldset>
            <legend>Recipient</legend>
            {candidate.contact_points.map((point) => (
              <div key={point.contact_point_id}>
                <input
                  type="radio"
                  id={`recipient-${point.contact_point_id}`}
                  name="recipient"
                  value={point.contact_point_id}
                  // Never pre-selected: ADR-008 approves an address the reviewer chose.
                  checked={chosen === point.contact_point_id}
                  disabled={!point.approvable}
                  onChange={() => {
                    setChosen(point.contact_point_id);
                  }}
                />
                <label htmlFor={`recipient-${point.contact_point_id}`}>{describe(point)}</label>
              </div>
            ))}
          </fieldset>

          {approvable.length === 0 && (
            <p role="alert">
              None of these addresses is verified, so this candidate cannot be approved yet.
            </p>
          )}

          <button
            type="submit"
            disabled={chosen === null || outcome.kind === "approving"}
            title={chosen === null ? "Choose the address this message would go to" : undefined}
          >
            {outcome.kind === "approving" ? "Approving…" : "Approve"}
          </button>
        </form>
      )}

      {outcome.kind === "refused" && <p role="alert">{outcome.detail}</p>}

      {outcome.kind === "approved" && (
        <div role="status">
          <p>
            Approved for <strong>{outcome.response.recipient}</strong>. A draft has been queued;
            nothing has been sent.
          </p>
        </div>
      )}
    </section>
  );
}
