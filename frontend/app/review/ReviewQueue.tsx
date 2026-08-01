import Link from "next/link";

import type { CandidateQueueRow, RevisionQueueRow } from "../../lib/api";

/**
 * The review queue (T-160; §12.3, §17.5, §19.6 Stage 2 exit gate).
 *
 * **Two queues, because the backend answers two questions.** `T-063a` lists candidates waiting
 * for a person to decide whether to write to them at all; `T-063b` lists message revisions
 * waiting for somebody to approve the exact words. They are separate lifecycles (ADR-015) and a
 * reviewer works them differently, so merging them into one list would invent a shared ordering
 * neither endpoint has.
 *
 * **Every row is a link, and that is the whole point of the screen.** Before this, a card could
 * only be opened by pasting a UUID somebody had fetched from the database. A revision row links
 * to its *candidate*, because the card is where the revision is reviewed — there is no
 * per-revision page, and inventing one would duplicate `T-064`'s card.
 *
 * **Backlog age is shown in whole hours, as the endpoint reports it.** §17.5 asks operational
 * views to expose review backlog and age; `T-063b` already rounds, deliberately, so formatting a
 * fractional age here would imply a precision the number does not have.
 *
 * **Empty is stated, never rendered as blank.** A page with nothing on it reads as "did not
 * load", and a reviewer who cannot tell those apart either waits for something that will never
 * come or assumes the system is broken. `total` comes from the endpoint, so a page showing ten of
 * forty says so rather than implying ten is all there is.
 *
 * It renders from props and fetches nothing; `lib/api.ts` is the only module that reaches the
 * backend (`tests/no-network.test.ts`).
 */

function CandidateQueue({ rows, total }: { rows: readonly CandidateQueueRow[]; total: number }) {
  return (
    <section aria-labelledby="candidate-queue">
      <h2 id="candidate-queue">Candidates awaiting review</h2>
      {rows.length === 0 ? (
        <p>No candidates are waiting for review.</p>
      ) : (
        <>
          <ul aria-label="Candidate queue">
            {rows.map((row) => (
              <li key={row.candidate_id}>
                <Link href={`/review/${row.candidate_id}`}>
                  {row.account_name} ({row.account_domain})
                </Link>
                {" — "}
                {row.contact_name ?? "no contact on this candidate"} · {row.campaign_name} ·{" "}
                {row.state}
              </li>
            ))}
          </ul>
          {total > rows.length && (
            <p>
              Showing {rows.length} of {total}. The rest are on later pages, which this screen does
              not offer yet.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function RevisionQueue({ rows, total }: { rows: readonly RevisionQueueRow[]; total: number }) {
  return (
    <section aria-labelledby="revision-queue">
      <h2 id="revision-queue">Messages awaiting approval</h2>
      {rows.length === 0 ? (
        <p>No message revisions are waiting for approval.</p>
      ) : (
        <>
          <ul aria-label="Revision queue">
            {rows.map((row) => (
              <li key={row.revision_id}>
                <Link href={`/review/${row.candidate_id}`}>{row.subject}</Link>
                {" — "}
                revision {row.revision_number} · {row.campaign_name} ·{" "}
                {row.opportunity_type ?? "opportunity type not yet qualified"} · waiting{" "}
                {row.backlog_age_hours} hours
              </li>
            ))}
          </ul>
          {total > rows.length && (
            <p>
              Showing {rows.length} of {total}. The rest are on later pages, which this screen does
              not offer yet.
            </p>
          )}
        </>
      )}
    </section>
  );
}

export function ReviewQueue({
  candidates,
  candidateTotal,
  revisions,
  revisionTotal,
}: {
  candidates: readonly CandidateQueueRow[];
  candidateTotal: number;
  revisions: readonly RevisionQueueRow[];
  revisionTotal: number;
}) {
  return (
    <>
      <p>
        Everything below is waiting on a person. Opening a card shows the evidence, the approved
        claims, and the exact draft; nothing is sent without an explicit approval.
      </p>
      <CandidateQueue rows={candidates} total={candidateTotal} />
      <RevisionQueue rows={revisions} total={revisionTotal} />
    </>
  );
}
