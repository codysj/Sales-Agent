import type { CandidateDetail } from "../../lib/api";
import { ApproveForm } from "./ApproveForm";
import { ApproveMessageForm } from "./ApproveMessageForm";
import { DecisionForm } from "./DecisionForm";
import { EditForm } from "./EditForm";
import { RefuseMessageForm } from "./RefuseMessageForm";

/**
 * The primary review card (T-064; §12.3 items 1–7).
 *
 * §12.3 lists seven things this must show, and the list is not a suggestion — it is what a
 * reviewer needs in order to approve responsibly. Each section below is labelled with its item
 * number so a reader can check the card against the specification without holding both in their
 * head, and `tests/review-card.test.tsx` asserts every one is present.
 *
 * **It renders from a prop and fetches nothing.** The data comes from `T-149`'s endpoint through
 * `lib/api.ts`, which is the only module permitted to reach the backend
 * (`tests/no-network.test.ts`). A component that fetched its own data would be a component you
 * cannot render in a test without a server.
 *
 * **Every action lives in its own form**, and item 7's structured reason lives in the form that
 * uses it rather than on the card. Which actions exist is the forms' business, not this
 * docstring's: it said "four of five are live, request-more-research is still shown disabled"
 * for days after `T-155` wired the fifth — while the `ACTIONS` comment eleven lines below said
 * the opposite (`T-214`). Two adjacent paragraphs disagreeing is what a count in prose buys.
 *
 * Two of the controls are about the *message* rather than the candidate — approving its exact
 * wording (`T-205`) and refusing it (`T-208`) — and that separation is deliberate: §11.3 and
 * ADR-008 make them decisions about two different objects.
 *
 * **Nothing is invented to fill a gap.** Absent readiness renders "not stated" rather than a
 * guess (GP-12: technical relevance is not availability); absent evidence renders "none recorded"
 * rather than an empty space (GP-02: missing facts remain missing); and the CRM relationship
 * renders "not checked" because there is no CRM adapter — ADR-004 makes HubSpot conditional on
 * `Q-001` and gate **G-05** is locked, so claiming "no relationship" would be an answer nobody
 * asked a system that could give it.
 */

/** §12.3 item 6. What each action would do once its task wires it. Edit is live (`T-065b`). */
/**
 * §12.3 item 6's five actions are all live now: edit (`T-065b`), approve (`T-154b`), reject and
 * defer (`T-066b2`), and request-more-research (`T-155`). Nothing is offered disabled any more,
 * so this list is empty — kept rather than deleted because the next action added to the card
 * belongs here first, disabled with its reason, before it belongs in a form.
 */
const ACTIONS: ReadonlyArray<readonly [string, string]> = [];

function formatInstant(value: string): string {
  // A reviewer judging whether evidence is stale needs the date, not a relative phrase that
  // rounds "yesterday" and "last month" toward each other.
  return new Date(value).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

/**
 * What the product's readiness word means for a message (`T-210`).
 *
 * `evaluation_or_pilot` is the database's word. Three rehearsal readers saw it on the card and
 * none could say what it permitted them to write — which matters here more than most vocabulary,
 * because GP-12 turns on it: technical relevance is not availability, and a reviewer who reads
 * this as "we sell it" will approve a message that says so.
 */
const READINESS: Record<string, string> = {
  not_ready: "Not ready to be offered at all.",
  technical_relevance_only: "Relevant to this kind of site, but not offered for purchase.",
  evaluation_or_pilot: "Offered for evaluation and pilot deployments, not for general purchase.",
  sellable_now: "Available to buy.",
};

/** What each revision state means for the person looking at it (`T-210`). */
const REVISION_STATE: Record<string, string> = {
  draft: "written, not yet checked",
  validation_failed: "checked and refused — it cannot be approved as written",
  review_pending: "waiting for you",
  approved: "approved",
  superseded: "replaced by a later revision",
  invalidated: "withdrawn — it cannot be approved",
};

export function ReviewCard({
  candidate,
  onChanged,
}: {
  candidate: CandidateDetail;
  /** Called after any action that changed something, so the page can refetch (`T-210`). */
  onChanged?: (() => void) | undefined;
}) {
  return (
    <article aria-label="Candidate review card">
      {/* Item 1 — account, contact, campaign, proposed opportunity type. */}
      <section aria-labelledby="who">
        <h2 id="who">Who this is</h2>
        <dl>
          <dt>Account</dt>
          <dd>
            {candidate.account_name} ({candidate.account_domain})
          </dd>
          <dt>Contact</dt>
          <dd>
            {candidate.contact_name ?? "No contact on this candidate"}
            {candidate.contact_role ? ` — ${candidate.contact_role}` : ""}
          </dd>
          <dt>Campaign</dt>
          <dd>{candidate.campaign_name}</dd>
          <dt>Proposed opportunity type</dt>
          <dd>{candidate.opportunity_type ?? "Not yet qualified"}</dd>
        </dl>
      </section>

      {/* Item 2 — strongest evidence, source quality, retrieval time. */}
      <section aria-labelledby="evidence">
        <h2 id="evidence">Evidence</h2>
        {candidate.evidence.length === 0 ? (
          <p>None recorded. Nothing here supports a statement about this prospect.</p>
        ) : (
          <ul>
            {candidate.evidence.map((row) => (
              <li key={row.evidence_id}>
                <blockquote>{row.excerpt}</blockquote>
                <p>
                  Source quality: <strong>{row.source_quality}</strong> · Retrieved:{" "}
                  <time dateTime={row.retrieved_at}>{formatInstant(row.retrieved_at)}</time>
                  {row.contains_personal_or_confidential_data
                    ? " · Contains personal or confidential data"
                    : ""}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Item 3 — product readiness and approved claims. */}
      <section aria-labelledby="product">
        <h2 id="product">Product</h2>
        <dl>
          <dt>Readiness</dt>
          <dd>
            {candidate.product_readiness === null
              ? "Not stated"
              : (READINESS[candidate.product_readiness] ?? "Not stated")}
            {candidate.product_readiness !== null && (
              <> (recorded as {candidate.product_readiness})</>
            )}
          </dd>
        </dl>
        <h3>Approved claims</h3>
        {candidate.approved_claims.length === 0 ? (
          <p>No approved claims are currently valid for this campaign.</p>
        ) : (
          <ul>
            {candidate.approved_claims.map((claim) => (
              <li key={claim.claim_id}>
                <p>{claim.text}</p>
                <p>
                  {claim.claim_key} v{claim.version}
                </p>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Item 4 — suppression and CRM warnings. */}
      <section aria-labelledby="warnings">
        <h2 id="warnings">Warnings</h2>
        {candidate.suppression.contact_suppressed || candidate.suppression.account_suppressed ? (
          <p role="alert">
            Suppressed:{" "}
            {[
              candidate.suppression.contact_suppressed ? "this contact" : null,
              candidate.suppression.account_suppressed ? "this account" : null,
            ]
              .filter(Boolean)
              .join(" and ")}
            . Do not approve outreach.
          </p>
        ) : (
          <p>No suppression recorded for this contact or account.</p>
        )}
        <p>
          Existing relationship with this account: <strong>not checked</strong>. No CRM is
          connected to this system, and connecting one is a decision nobody has taken yet — so
          this is "nobody asked", not "no relationship". (Open question Q-001; gate G-05.)
        </p>
      </section>

      {/* Item 5 — the exact revision, and what happens next. */}
      <section aria-labelledby="message">
        <h2 id="message">Exact message</h2>
        {candidate.current_revision === null ? (
          // `T-210`, and the contradiction that made it P2. Approving queues a draft, the worker
          // writes it moments later, and this said "no draft has been written" the whole time —
          // directly under a message saying one had been queued. Two of three rehearsal runs saw
          // both sentences at once; the third found the draft "by guessing".
          candidate.state === "approved" ? (
            <>
              <p>
                A draft has been queued for this candidate and is being written. It does not exist
                yet, which is why there is nothing to read here.
              </p>
              {onChanged && (
                <button
                  type="button"
                  onClick={() => {
                    onChanged();
                  }}
                >
                  Check for the draft
                </button>
              )}
            </>
          ) : (
            <p>
              No draft has been written for this candidate yet. One is queued when the candidate is
              approved for outreach.
            </p>
          )
        ) : (
          <>
            <p>
              Revision {candidate.current_revision.revision_number} —{" "}
              {REVISION_STATE[candidate.current_revision.state] ?? candidate.current_revision.state}{" "}
              (recorded as {candidate.current_revision.state})
            </p>
            <p>Subject: {candidate.current_revision.subject}</p>
            <pre>{candidate.current_revision.body}</pre>
          </>
        )}
        <p>
          <strong>What happens next:</strong> {candidate.what_happens_next}
        </p>
      </section>

      {/* Item 6 — any action not yet built, offered disabled with its reason. Empty today. */}
      {ACTIONS.length > 0 && (
        <section aria-labelledby="actions">
          <h2 id="actions">Actions</h2>
          {ACTIONS.map(([label, why]) => (
            <button key={label} type="button" disabled title={why}>
              {label}
            </button>
          ))}
        </section>
      )}

      {/* Item 6 — approving, for an address the reviewer picks (ADR-008). */}
      <ApproveForm candidate={candidate} onChanged={onChanged} />

      {/* Items 6 and 7 — rejecting and deferring, each with a §10.6 reason. */}
      <DecisionForm candidate={candidate} onChanged={onChanged} />

      {/* Item 6 — approving the exact words, the second of the two approvals (T-205). Placed
          before editing because approving is what a reviewer who agrees with the draft wants,
          and editing is the exception. */}
      <ApproveMessageForm candidate={candidate} onChanged={onChanged} />

      {/* Items 6 and 7 — refusing the words, with a §10.6 reason and no replacement (T-208).
          Between approving and editing because that is the order a reviewer decides in: yes,
          no, or here is better wording. */}
      <RefuseMessageForm candidate={candidate} onChanged={onChanged} />

      {/* Items 6 and 7 — editing, and the structured correction reason it requires. */}
      {candidate.current_revision !== null && (
        <EditForm revision={candidate.current_revision} onChanged={onChanged} />
      )}
    </article>
  );
}
