"use client";

import { useState } from "react";

import { EditRejected, editRevision } from "../../lib/api";
import type { CandidateDetail, EditResponse } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

/**
 * The editing form (T-065b; §12.3 items 5–7, §10.5).
 *
 * §10.5: editing an approved message creates a new immutable revision and invalidates the prior
 * approval. The backend does all of that (`T-065a`); this is the surface a reviewer uses, and its
 * job is to be honest about what happened afterwards.
 *
 * **A correction reason is required by the browser, not only by the server.** The `required`
 * attribute on the select is what §12.3 item 7 asks for at the point of entry — a native
 * constraint the browser enforces before any request leaves, with the server's own refusal behind
 * it as the guard that actually binds. Two independent checks, and the near one gives a reviewer
 * the message immediately.
 *
 * **A validation failure is shown as the check that failed.** `T-055` names its checks —
 * `claim_citations`, `product_readiness`, `product_statement_grounding`, `compliance_elements` —
 * and a reviewer who is told "validation failed" has to guess which sentence to fix. The revision
 * still exists in `validation_failed`, so the form says that too: the edit was *saved* and is not
 * approvable, which is a different thing from the edit being lost.
 *
 * **The record version goes back with the edit.** The card was rendered at some moment; if the
 * revision moved since, `T-065a` answers 409 and the reviewer reloads rather than overwriting
 * text they never read.
 *
 * **Without a session token it refuses to submit.** `T-065a` requires a bearer token on
 * mutations and `T-151` is the sign-in screen that will supply one. Until then there is no token
 * in a real browser, and saying so beats posting an unauthenticated request and rendering a 401.
 */

/** §12.3 item 7. The reasons a correction may cite, shared with the card's disabled preview. */
export const CORRECTION_REASONS: ReadonlyArray<string> = [
  "Evidence does not support the claim",
  "Wrong contact or account",
  "Product readiness misstated",
  "Tone or wording",
  "Timing",
  "Other",
];

type Outcome =
  | { kind: "idle" }
  | { kind: "saving" }
  | { kind: "saved"; response: EditResponse }
  | { kind: "refused"; detail: string };

export function EditForm({ revision }: { revision: NonNullable<CandidateDetail["current_revision"]> }) {
  const [subject, setSubject] = useState(revision.subject);
  const [body, setBody] = useState(revision.body);
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const token = getSessionToken();
    if (token === null) {
      setOutcome({
        kind: "refused",
        detail:
          "You are not signed in, so this edit was not sent. Sign-in is not built yet (T-151); " +
          "nothing was changed.",
      });
      return;
    }

    setOutcome({ kind: "saving" });
    try {
      const response = await editRevision(
        revision.revision_id,
        {
          subject,
          body,
          correction_reason: reason,
          record_version: revision.record_version,
        },
        token,
      );
      setOutcome({ kind: "saved", response });
    } catch (error) {
      setOutcome({
        kind: "refused",
        detail:
          error instanceof EditRejected
            ? error.detail
            : `The edit could not be sent: ${String(error)}`,
      });
    }
  }

  return (
    <section aria-labelledby="edit">
      <h2 id="edit">Edit this draft</h2>
      <p>
        Editing creates revision {revision.revision_number + 1} and supersedes this one. Any
        approval on the current revision stops being usable (§10.5).
      </p>

      <form
        onSubmit={(event) => {
          // `void`: the handler is async, and a form's `onSubmit` wants nothing back. Returning
          // the promise would make React ignore a rejection nobody is watching.
          void submit(event);
        }}
        aria-label="Edit draft"
      >
        <label htmlFor="edit-subject">Subject</label>
        <input
          id="edit-subject"
          name="subject"
          value={subject}
          required
          onChange={(event) => {
            setSubject(event.target.value);
          }}
        />

        <label htmlFor="edit-body">Body</label>
        <textarea
          id="edit-body"
          name="body"
          value={body}
          required
          rows={12}
          onChange={(event) => {
            setBody(event.target.value);
          }}
        />

        {/* §12.3 item 7 — required at the point of entry, and again at the server. */}
        <label htmlFor="correction-reason">Why is this being corrected?</label>
        <select
          id="correction-reason"
          name="correction_reason"
          value={reason}
          required
          onChange={(event) => {
            setReason(event.target.value);
          }}
        >
          <option value="">Select a reason</option>
          {CORRECTION_REASONS.map((each) => (
            <option key={each} value={each}>
              {each}
            </option>
          ))}
        </select>

        <button type="submit" disabled={outcome.kind === "saving"}>
          {outcome.kind === "saving" ? "Saving…" : "Save as a new revision"}
        </button>
      </form>

      {outcome.kind === "refused" && <p role="alert">{outcome.detail}</p>}

      {outcome.kind === "saved" && <EditOutcome response={outcome.response} />}
    </section>
  );
}

/** What the edit did. Exported so it can be rendered on its own in a test. */
export function EditOutcome({ response }: { response: EditResponse }) {
  const retired = response.revoked_approvals.length + response.expired_approvals.length;

  return (
    <div role="status">
      <p>
        Saved as revision {response.revision.revision_number}. Revision{" "}
        {response.revision.revision_number - 1} is superseded and can no longer be approved.
      </p>

      {retired > 0 && (
        <p>
          {retired === 1 ? "One approval" : `${String(retired)} approvals`} on the previous revision{" "}
          {retired === 1 ? "was" : "were"} retired, because an approval names the exact text it was
          given (§10.5).
        </p>
      )}

      {response.is_valid ? (
        <p>Validation passed. This revision can be approved.</p>
      ) : (
        <>
          <p role="alert">
            Saved, but validation failed — this revision cannot be approved until it is corrected.
            It is stored as revision {response.revision.revision_number} in{" "}
            {response.revision.state}, so nothing you wrote was lost.
          </p>
          <ul aria-label="Failed validation checks">
            {response.failed_checks.map((check) => (
              <li key={check}>{CHECK_EXPLANATIONS[check] ?? check}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

/**
 * `T-055`'s check names, each in a sentence a reviewer can act on.
 *
 * The identifier is kept in the text rather than replaced by it: the reviewer reads the sentence,
 * and anyone they escalate to searches the identifier. The keys are the backend's `Check` values,
 * and `backend/tests/test_review_edit.py` asserts this map covers every one of them — a check
 * added on the backend and forgotten here would otherwise reach a reviewer as a bare identifier.
 *
 * A key that is missing anyway renders verbatim. A check nobody has written a sentence for is
 * still more useful named than swallowed, and inventing an explanation for one would be worse
 * than showing its identifier.
 */
export const CHECK_EXPLANATIONS: Readonly<Record<string, string>> = {
  claim_citations:
    "claim_citations — a product sentence cites a claim that is not approved, or cites none at all.",
  claim_currency: "claim_currency — a cited claim has expired or been superseded.",
  campaign_scope: "campaign_scope — a cited claim is not approved for this campaign.",
  product_readiness:
    "product_readiness — the message implies availability the product status does not support.",
  evidence_citations:
    "evidence_citations — a statement about this prospect cites no evidence to support it.",
  recipient_contactable:
    "recipient_contactable — the recipient address is not verified, so it must not be used.",
  suppression: "suppression — this recipient is suppressed and must not be contacted.",
  product_statement_grounding:
    "product_statement_grounding — a product statement is not grounded in an approved claim.",
  compliance_elements:
    "compliance_elements — a required compliance element is missing from the message.",
};
