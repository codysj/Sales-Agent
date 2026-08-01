"use client";

import { useState } from "react";

import { ApiRefused, approveCandidate } from "../../lib/api";
import type { ApproveResponse, CandidateDetail, ContactPointRow } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

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

export function ApproveForm({ candidate }: { candidate: CandidateDetail }) {
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
        detail:
          "You are not signed in, so nothing was approved. Sign in and try again (T-151).",
      });
      return;
    }

    setOutcome({ kind: "approving" });
    try {
      const response = await approveCandidate(
        candidate.candidate_id,
        { recipient_contact_point_id: chosen, record_version: candidate.record_version },
        token,
      );
      setOutcome({ kind: "approved", response });
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

  return (
    <section aria-labelledby="approve">
      <h2 id="approve">Approve for outreach</h2>
      <p>
        Approving queues a draft for the address you choose. Nothing is sent — live sending is
        gated (G-07) and needs a separate, explicit authorization.
      </p>

      {candidate.contact_points.length === 0 ? (
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
