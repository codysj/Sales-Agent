import Link from "next/link";

import type { StrandedRevisionRow } from "../../lib/api";

/**
 * Drafts that cannot be approved by anyone, and the way back (T-209, T-208; §7.5, §8.2, §12.3).
 *
 * The other half of §7.5's flag. `AttentionList` shows approvals that no longer authorize a send;
 * this shows candidates whose latest draft failed validation, which `T-071d` found were in no
 * list at all: the review queue holds `review_pending`, editing is a one-way door (§8.2 has no
 * un-supersede, correctly), and so a failed edit left the candidate waiting on nobody while the
 * candidate-level approval still stood.
 *
 * **Every row says what to do next, and only things that can actually be done.** Two of the three
 * rehearsal runs reached this dead end and neither found a route out — one spent five revisions
 * against an error naming no sentence. Editing is the way back and always was for a
 * `validation_failed` revision; it had simply never been said anywhere a reviewer would read it.
 *
 * These rows used to end "or reject the candidate if it should not be written to at all", which
 * was **never possible** for anything on this page (`T-211`): a candidate only gets a draft by
 * being approved (`campaigns/approval.py` is what enqueues drafting), and §8.2 gives an approved
 * candidate one edge, to `invalidated`. Advice that cannot be followed is worse than none — a
 * reviewer spends the attempt before finding out.
 *
 * **The checks are glossed, not printed raw.** `product_statement_grounding` is the system's name
 * for the rule, and a reviewer holding no specification cannot act on it. The raw name stays
 * beside the sentence so somebody debugging can still search for it — that is the same trade
 * `AttentionList` makes with its triggers.
 *
 * **It renders from a prop and fetches nothing**, like every other component here: `lib/api.ts` is
 * the only module permitted to reach the backend (`tests/no-network.test.ts`).
 */

type CheckName = StrandedRevisionRow["failures"][number]["check"];

/**
 * What each §8.3 step 10 check means in a sentence a reviewer can act on.
 *
 * Keyed by the generated union rather than by `string`, so a check added to the backend fails
 * `npm run typecheck` here instead of rendering as a blank explanation. A runtime fallback would
 * have been the softer option and the wrong one: "no reason given" is the failure `T-209` exists
 * to end, and it should not be reachable by forgetting something.
 */
const CHECKS: Record<CheckName, string> = {
  claim_citations: "A claim this message cites no longer exists.",
  claim_currency: "A claim this message cites has expired or is due for review.",
  campaign_scope: "A claim this message cites is not approved for this campaign.",
  product_readiness: "The product is not currently ready for the kind of outreach this message makes.",
  evidence_citations: "A piece of evidence this message rests on is missing or out of date.",
  evidence_for_personalization:
    "The message says something about this prospect without pointing at the recorded fact it comes from.",
  recipient_contactable: "The recipient address cannot be written to — it is unverified, or not an email address.",
  suppression: "This contact or account is suppressed. Nothing may be sent to them.",
  product_statement_grounding:
    "The message body says something about the product that is not one of the approved claims it cites, word for word.",
  compliance_elements: "The message is missing something it is required to contain.",
};

/** §10.6's three message-level categories, in a reviewer's words (`T-208`). */
const REFUSAL_REASONS: Record<string, string> = {
  tone_or_positioning_problem: "the tone or positioning was wrong",
  unsupported_claim: "it said something the business cannot support",
  personalization_not_useful: "the personalization was not useful",
};

function RefusedByAPerson({ row }: { row: StrandedRevisionRow }) {
  const reason = row.refusal_reason ?? "";
  return (
    <>
      <h4>Why it cannot be approved</h4>
      <p>
        A reviewer decided these words should not be sent:{" "}
        {REFUSAL_REASONS[reason] ?? "they refused the wording"}.
      </p>
      {row.refusal_notes !== null && <blockquote>{row.refusal_notes}</blockquote>}
      <p>
        Nothing writes a replacement by itself, so this candidate has no message anyone can
        approve.{" "}
        <Link href={`/review/${row.candidate_id}`}>Open this candidate</Link> and edit the draft to
        write one.
      </p>
    </>
  );
}

function RefusedByACheck({ row }: { row: StrandedRevisionRow }) {
  return (
    <>
      <h4>Why it cannot be approved</h4>
      <ul>
        {row.failures.map((failure) => (
          <li key={failure.check}>
            <p>{CHECKS[failure.check]}</p>
            {/* The system's own words, kept for whoever has to debug this, and labelled as such
                so a reviewer knows they are not being asked to understand them. */}
            <p>
              Recorded as <code>{failure.check}</code>: {failure.reason}
            </p>
          </li>
        ))}
      </ul>

      <p>
        <Link href={`/review/${row.candidate_id}`}>Open this candidate</Link> and edit the draft
        again — a draft that failed validation can still be edited. Nothing about it will move
        until somebody does.
      </p>
    </>
  );
}

function StrandedRevision({ row }: { row: StrandedRevisionRow }) {
  return (
    <li>
      <h3>
        {row.account_name} — {row.campaign_name}
      </h3>
      <p>
        Revision {row.revision_number}. Subject: {row.subject}
      </p>

      {/* Two different situations wanting two different reactions: a draft that broke, and a
          decision a person already took. A row that showed them identically would ask a reviewer
          to redo a judgement that has been made. */}
      {row.refusal_reason === null ? (
        <RefusedByACheck row={row} />
      ) : (
        <RefusedByAPerson row={row} />
      )}
    </li>
  );
}

export function StrandedRevisionList({ rows }: { rows: readonly StrandedRevisionRow[] }) {
  return (
    <section aria-labelledby="stranded">
      <h2 id="stranded">Drafts nobody can approve</h2>
      <p>
        Each of these is the latest draft for its candidate, and either a validation check refused
        it or a reviewer did. Either way there is nothing here anyone can approve, and no review
        queue holds them — this is the only place they appear.
      </p>

      {rows.length === 0 ? (
        <p>
          No draft is stuck. Every candidate that has a draft has one that can still be approved or
          edited.
        </p>
      ) : (
        <ul aria-label="Stranded drafts">
          {rows.map((row) => (
            <StrandedRevision key={row.revision_id} row={row} />
          ))}
        </ul>
      )}
    </section>
  );
}
