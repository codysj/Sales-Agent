"use client";

import { useState } from "react";

import { ApiRefused, deferCandidate, rejectCandidate, requestMoreResearch } from "../../lib/api";
import type { CandidateDetail, DecisionCategory, DecisionResponse } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

/**
 * Rejecting and deferring, with the reason §10.6 asks for (T-066b2; §12.3 items 6 and 7, §10.6).
 *
 * **The eleven categories are labelled here and nowhere else.** The *list* comes from the
 * generated `DecisionCategory` type, so a category added on the backend is a compile error here
 * rather than an option a reviewer never sees — `CATEGORY_LABELS` is typed as a total record, and
 * `tsc` refuses a missing key. What this file owns is the wording a human reads; what the backend
 * owns is which categories exist. Neither can drift without the other failing.
 *
 * **A rejection is required to name one, twice over.** The `required` attribute stops the browser
 * submitting, and `T-066b1`'s schema refuses a request without it. The near check gives the
 * reviewer the message immediately; the far one is what actually binds.
 *
 * **A deferral must say what it waits for.** §10.6's eleventh category is "defer until a specific
 * date/event", and a deferral with neither leaves review with nothing to bring it back — so the
 * form will not submit one, and the server refuses it too. Both shapes are offered because they
 * are genuinely different: a date for "after their fiscal year", an event for "when they publish
 * their storage roadmap", which has no date yet.
 *
 * **Requesting more research is here too, and it is not a decision about the candidate's fate.**
 * ADR-022: it queues an evidence pass and moves the candidate nowhere, so the card stays where the
 * reviewer is looking. It shares the category select because §10.6 structures this reason as well —
 * "why did somebody want more evidence here" is exactly the evaluation data that list collects.
 *
 * **Both decisions are shown back in the reviewer's own terms.** A deferral confirmed as "done"
 * tells nobody when it comes back; one confirmed as "deferred until 2026-12-01" can be checked at
 * a glance and corrected if it was a slip.
 */

/** §10.6's categories in a reviewer's words. Total over `DecisionCategory` by construction. */
const CATEGORY_LABELS: Record<DecisionCategory, string> = {
  wrong_campaign: "Wrong campaign",
  wrong_account_or_duplicate: "Wrong account, or a duplicate",
  poor_buyer_role: "Poor buyer role",
  weak_or_stale_evidence: "Weak or stale evidence",
  product_not_ready: "Product not ready",
  unsupported_claim: "Unsupported claim",
  personalization_not_useful: "Personalization not useful",
  tone_or_positioning_problem: "Tone or positioning problem",
  existing_relationship: "Existing relationship",
  compliance_or_suppression_concern: "Compliance or suppression concern",
  defer_until_date_or_event: "Defer until a specific date or event",
};

/**
 * The categories a *rejection* may cite.
 *
 * All of §10.6's except the eleventh: `T-066a` refuses "defer until a date or event" as a
 * rejection reason, because a candidate rejected for waiting is one nobody will look at again.
 * Offering it here would mean showing a reviewer an option the server rejects.
 */
const REJECTION_CATEGORIES = (Object.keys(CATEGORY_LABELS) as DecisionCategory[]).filter(
  (category) => category !== "defer_until_date_or_event",
);

type Outcome =
  | { kind: "idle" }
  | { kind: "deciding" }
  | { kind: "decided"; response: DecisionResponse }
  | { kind: "refused"; detail: string };

export function DecisionForm({ candidate }: { candidate: CandidateDetail }) {
  const [category, setCategory] = useState<DecisionCategory | "">("");
  const [notes, setNotes] = useState("");
  const [untilDate, setUntilDate] = useState("");
  const [untilEvent, setUntilEvent] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const busy = outcome.kind === "deciding";
  const waypoint = untilDate !== "" || untilEvent.trim() !== "";

  async function send(run: (token: string) => Promise<DecisionResponse>) {
    const token = getSessionToken();
    if (token === null) {
      setOutcome({
        kind: "refused",
        detail: "You are not signed in, so nothing was recorded. Sign in and try again (T-151).",
      });
      return;
    }
    setOutcome({ kind: "deciding" });
    try {
      setOutcome({ kind: "decided", response: await run(token) });
    } catch (error) {
      setOutcome({
        kind: "refused",
        detail:
          error instanceof ApiRefused
            ? error.detail
            : `The decision could not be sent: ${String(error)}`,
      });
    }
  }

  async function reject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (category === "") {
      return;
    }
    await send((token) =>
      rejectCandidate(
        candidate.candidate_id,
        {
          category,
          notes: notes.trim() === "" ? null : notes,
          record_version: candidate.record_version,
        },
        token,
      ),
    );
  }

  async function askForResearch() {
    // This guard is a **type narrowing**, not a runtime defence: `category` is
    // `DecisionCategory | ""` and the request field is not. Its runtime branch is unreachable —
    // the button is disabled while `category === ""`, and unlike `reject` and `defer` there is no
    // form-submit path that fires past a disabled button — which a control confirmed by deleting
    // it and failing no test. Kept because `tsc` needs it; recorded as narrowing so nobody reads
    // it as a check that has been proven to work.
    if (category === "") {
      return;
    }
    await send((token) =>
      requestMoreResearch(
        candidate.candidate_id,
        {
          category,
          notes: notes.trim() === "" ? null : notes,
          record_version: candidate.record_version,
        },
        token,
      ),
    );
  }

  async function defer(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!waypoint) {
      return;
    }
    await send((token) =>
      deferCandidate(
        candidate.candidate_id,
        {
          until_date: untilDate === "" ? null : untilDate,
          until_event: untilEvent.trim() === "" ? null : untilEvent,
          category: category === "" ? "defer_until_date_or_event" : category,
          notes: notes.trim() === "" ? null : notes,
          record_version: candidate.record_version,
        },
        token,
      ),
    );
  }

  return (
    <section aria-labelledby="decide">
      <h2 id="decide">Reject or defer</h2>

      <form
        onSubmit={(event) => {
          void reject(event);
        }}
        aria-label="Reject candidate"
      >
        {/* §12.3 item 7 — required at the point of entry, and again at the server. */}
        <label htmlFor="decision-category">Why is this being rejected?</label>
        <select
          id="decision-category"
          name="category"
          value={category}
          required
          onChange={(event) => {
            setCategory(event.target.value as DecisionCategory | "");
          }}
        >
          <option value="">Select a reason</option>
          {REJECTION_CATEGORIES.map((each) => (
            <option key={each} value={each}>
              {CATEGORY_LABELS[each]}
            </option>
          ))}
        </select>

        <label htmlFor="decision-notes">Notes (optional)</label>
        <textarea
          id="decision-notes"
          name="notes"
          value={notes}
          rows={3}
          onChange={(event) => {
            setNotes(event.target.value);
          }}
        />

        <button
          type="submit"
          disabled={category === "" || busy}
          title={
            category === ""
              ? "Choose a reason first — it is recorded with the rejection (§10.6)"
              : undefined
          }
        >
          {busy ? "Recording…" : "Reject"}
        </button>

        {/* Same form, because it needs the same category and notes — but `type="button"`, so it
            never submits the rejection. A reviewer asking for more evidence is not rejecting. */}
        <button
          type="button"
          disabled={category === "" || busy}
          title={
            category === ""
              ? "Choose a reason first — it is recorded with the request (§10.6)"
              : undefined
          }
          onClick={() => {
            void askForResearch();
          }}
        >
          {busy ? "Recording…" : "Request more research"}
        </button>
      </form>

      <form
        onSubmit={(event) => {
          void defer(event);
        }}
        aria-label="Defer candidate"
      >
        <label htmlFor="defer-until-date">Defer until a date</label>
        <input
          id="defer-until-date"
          name="until_date"
          type="date"
          value={untilDate}
          onChange={(event) => {
            setUntilDate(event.target.value);
          }}
        />

        <label htmlFor="defer-until-event">…or until an event</label>
        <input
          id="defer-until-event"
          name="until_event"
          type="text"
          value={untilEvent}
          maxLength={500}
          onChange={(event) => {
            setUntilEvent(event.target.value);
          }}
        />

        <button
          type="submit"
          disabled={!waypoint || busy}
          title={
            waypoint
              ? undefined
              : "A deferral needs a date or an event; without one nothing brings this candidate back"
          }
        >
          {busy ? "Recording…" : "Defer"}
        </button>
      </form>

      {outcome.kind === "refused" && <p role="alert">{outcome.detail}</p>}

      {outcome.kind === "decided" && <DecisionOutcome response={outcome.response} />}
    </section>
  );
}

/** What was recorded, in the reviewer's own terms. Exported so it can be rendered on its own. */
export function DecisionOutcome({ response }: { response: DecisionResponse }) {
  return (
    <div role="status">
      {response.kind === "request_research" ? (
        <p>
          More research requested: <strong>{CATEGORY_LABELS[response.category]}</strong>. One
          evidence pass is queued; this candidate stays in review.
        </p>
      ) : response.kind === "reject" ? (
        <p>
          Rejected: <strong>{CATEGORY_LABELS[response.category]}</strong>. This candidate is
          closed.
        </p>
      ) : (
        <p>
          Deferred until{" "}
          <strong>{response.defer_until_date ?? response.defer_until_event}</strong>, as{" "}
          {CATEGORY_LABELS[response.category]}.
        </p>
      )}
      {response.notes !== null && <p>Notes: {response.notes}</p>}
    </div>
  );
}
