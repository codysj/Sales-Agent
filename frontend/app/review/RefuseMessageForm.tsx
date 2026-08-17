"use client";

import { useState } from "react";

import { ApiRefused, refuseRevision } from "../../lib/api";
import type { CandidateDetail, RefuseMessageRequest, RefuseMessageResponse } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

/**
 * Refusing the words, without writing replacements (T-208; §12.3 items 6-7, §10.6, §8.2).
 *
 * **Why this exists.** `T-071d` put three readers in front of a draft and all three decided it
 * must not go out. **None could record that.** The card offered *approve these words* and *edit
 * this draft*, so a refusal could only be expressed by authoring replacement copy — and a
 * reviewer who thinks the wording is wrong but has no better wording had nothing to press. One
 * asked, in as many words, why there was no way to say "these words should never be sent".
 *
 * **It is not rejecting the candidate**, and the wording says so twice. All three runs approved
 * the company on its evidence and refused only the message. `DecisionForm` is where the company
 * is rejected; this decides about a paragraph.
 *
 * **Three reasons, not eleven.** §10.6's other eight are about the candidate — its campaign, its
 * account, its buyer role — and the backend's schema refuses them here. Offering them would let a
 * reviewer file a true statement against the wrong object.
 *
 * **It says what happens next, in the backend's own sentence.** Nothing writes a replacement
 * automatically, so a refusal leaves the candidate with no approvable draft; the server is the
 * one place that knows that and says it.
 */

type Outcome =
  | { kind: "idle" }
  | { kind: "refusing" }
  | { kind: "refused"; response: RefuseMessageResponse }
  | { kind: "rejected"; detail: string };

/** Revision states a reviewer can still refuse from — `REFUSABLE_STATES` on the server. */
const REFUSABLE: readonly string[] = ["review_pending", "validation_failed"];

/** §10.6's three message-level categories, labelled for a reader rather than a database. */
const REASONS: ReadonlyArray<readonly [RefuseMessageRequest["reason"], string]> = [
  ["tone_or_positioning_problem", "The tone or positioning is wrong"],
  ["unsupported_claim", "It says something we cannot support"],
  ["personalization_not_useful", "The personalization is not useful"],
];

export function RefuseMessageForm({
  candidate,
  onChanged,
}: {
  candidate: CandidateDetail;
  onChanged?: (() => void) | undefined;
}) {
  const [reason, setReason] = useState<RefuseMessageRequest["reason"] | "">("");
  const [notes, setNotes] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const revision = candidate.current_revision;
  if (revision === null || !REFUSABLE.includes(revision.state)) {
    return null;
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason === "" || revision === null) {
      return;
    }
    const token = getSessionToken();
    if (token === null) {
      setOutcome({
        kind: "rejected",
        detail: "You are not signed in, so nothing was recorded. Sign in and try again.",
      });
      return;
    }

    setOutcome({ kind: "refusing" });
    try {
      const response = await refuseRevision(
        revision.revision_id,
        {
          reason,
          ...(notes.trim() === "" ? {} : { notes: notes.trim() }),
          // The same guarantee the approve control gives: you are deciding about the text you
          // were shown, or you are told it moved.
          record_version: revision.record_version,
        },
        token,
      );
      setOutcome({ kind: "refused", response });
      onChanged?.();
    } catch (error) {
      setOutcome({
        kind: "rejected",
        detail:
          error instanceof ApiRefused
            ? error.detail
            : `The refusal could not be sent: ${String(error)}`,
      });
    }
  }

  return (
    <section aria-labelledby="refuse-message">
      <h2 id="refuse-message">These words should not be sent</h2>
      <p>
        Use this when the message is wrong and you have no better wording to offer. It records the
        decision against revision {revision.revision_number} and nothing else — the candidate stays
        exactly as it is, and this is not a rejection of the company.
      </p>

      {outcome.kind === "refused" ? (
        <div role="status">
          <p>Recorded. Revision {revision.revision_number} can no longer be approved.</p>
          <p>{outcome.response.what_happens_next}</p>
        </div>
      ) : (
        <form
          onSubmit={(event) => {
            void submit(event);
          }}
          aria-label="Refuse message"
        >
          <label htmlFor="refusal-reason">What is wrong with these words?</label>
          <select
            id="refusal-reason"
            value={reason}
            onChange={(event) => {
              setReason(event.target.value as RefuseMessageRequest["reason"]);
            }}
          >
            <option value="">Select a reason</option>
            {REASONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>

          <label htmlFor="refusal-notes">Anything to add? (optional)</label>
          <input
            type="text"
            id="refusal-notes"
            value={notes}
            onChange={(event) => {
              setNotes(event.target.value);
            }}
          />

          <button
            type="submit"
            disabled={reason === "" || outcome.kind === "refusing"}
            title={reason === "" ? "A refusal needs a reason (§10.6)" : undefined}
          >
            {outcome.kind === "refusing" ? "Recording…" : "Do not send these words"}
          </button>
        </form>
      )}

      {outcome.kind === "rejected" && <p role="alert">{outcome.detail}</p>}
    </section>
  );
}
