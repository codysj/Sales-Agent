"use client";

import { useState } from "react";

import { ApiRefused, revokeApproval } from "../../lib/api";
import type { AttentionRow } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

/**
 * Approvals that no longer authorize a send, and the way to close one out (T-068b; §7.5, §8.4,
 * §17.6).
 *
 * **The triggering record is shown, not just the category.** `T-068a` made the endpoint carry
 * `triggering_id` for exactly this reason: "approved claim set has been superseded" tells a
 * reviewer what *kind* of thing went wrong, and leaves them with an investigation to start. The
 * identifier of the record that changed is what ends it. Two triggers name no other row — an
 * approval that expired, and one whose own state moved — and those say so rather than rendering a
 * blank cell that reads like missing data.
 *
 * **Revoking asks for a reason and will not proceed without one.** §17.6 wants operational actions
 * explicable; the backend refuses an empty reason, and a button that let a reviewer discover that
 * by being refused would be a button that wasted their decision. The `record_version` the reviewer
 * was shown goes with it, so revoking something that changed underneath them is a refusal they can
 * read rather than a silent overwrite.
 *
 * **A revoked row leaves the list.** It is no longer an attention item — somebody dealt with it —
 * and leaving it there would bury the ones nobody has looked at, which is the failure this list
 * exists to prevent. Removed locally rather than by refetching: the reviewer's other rows may have
 * half-typed reasons in them, and reloading would discard work they are in the middle of.
 *
 * **It renders from a prop and fetches its own list from nowhere.** The page loads the rows; this
 * shows them. `lib/api.ts` remains the only module that reaches the backend
 * (`tests/no-network.test.ts`), and the one call made here goes through it.
 */

/** What each trigger means in a sentence a reviewer can act on, and what `triggering_id` names. */
const TRIGGERS: Record<AttentionRow["trigger"], { what: string; names: string | null }> = {
  not_approved: {
    what: "This approval is no longer in the approved state.",
    names: null,
  },
  expired: {
    what: "This approval passed its expiry.",
    names: null,
  },
  revision_missing: {
    what: "The approved revision no longer exists.",
    names: "Missing revision",
  },
  revision_retired: {
    what: "The approved revision was superseded or invalidated.",
    names: "Revision",
  },
  content_changed: {
    what: "The message text changed after it was approved.",
    names: "Revision",
  },
  recipient_changed: {
    what: "The recipient changed after the approval was granted.",
    names: "Recipient contact point",
  },
  product_status_superseded: {
    what: "The product readiness version this was approved against is no longer effective.",
    names: "Product status version",
  },
  claim_set_superseded: {
    what: "The approved claim set this was approved against has been superseded.",
    names: "Approved claim set",
  },
};

type Outcome =
  | { kind: "idle" }
  | { kind: "revoking" }
  | { kind: "refused"; detail: string };

function formatInstant(value: string): string {
  return new Date(value).toISOString().replace("T", " ").slice(0, 16) + " UTC";
}

function StaleApproval({ row, onRevoked }: { row: AttentionRow; onRevoked: () => void }) {
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  const trigger = TRIGGERS[row.trigger];

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === "") {
      return;
    }
    const token = getSessionToken();
    if (token === null) {
      setOutcome({
        kind: "refused",
        detail: "You are not signed in, so nothing was revoked. Sign in and try again (T-151).",
      });
      return;
    }

    setOutcome({ kind: "revoking" });
    try {
      await revokeApproval(
        row.approval_id,
        { reason, record_version: row.record_version },
        token,
      );
      onRevoked();
    } catch (error) {
      setOutcome({
        kind: "refused",
        detail:
          error instanceof ApiRefused
            ? error.detail
            : `The revocation could not be sent: ${String(error)}`,
      });
    }
  }

  return (
    <li>
      <h3>{trigger.what}</h3>
      <dl>
        <dt>Why the application flagged it</dt>
        <dd>{row.reason}</dd>
        <dt>{trigger.names ?? "Triggering record"}</dt>
        <dd>
          {/* Never a bare blank: "no other record is involved" and "we failed to load one" look
              identical as an empty cell, and they need different reactions. */}
          {row.triggering_id ??
            "None — this is a fact about the approval itself, not about another record."}
        </dd>
        <dt>Approved revision</dt>
        <dd>{row.message_revision_id}</dd>
        <dt>Approved by</dt>
        <dd>{row.approver_id}</dd>
        <dt>Approval expires</dt>
        <dd>
          <time dateTime={row.approval_expires_at}>{formatInstant(row.approval_expires_at)}</time>
        </dd>
      </dl>

      <form
        onSubmit={(event) => {
          void submit(event);
        }}
        aria-label={`Revoke approval ${row.approval_id}`}
      >
        <label htmlFor={`reason-${row.approval_id}`}>Why are you revoking this?</label>
        <input
          type="text"
          id={`reason-${row.approval_id}`}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
        <button
          type="submit"
          disabled={reason.trim() === "" || outcome.kind === "revoking"}
          title={reason.trim() === "" ? "A revocation needs a reason (§17.6)" : undefined}
        >
          {outcome.kind === "revoking" ? "Revoking…" : "Revoke"}
        </button>
      </form>

      {outcome.kind === "refused" && <p role="alert">{outcome.detail}</p>}
    </li>
  );
}

export function AttentionList({ rows }: { rows: readonly AttentionRow[] }) {
  const [revoked, setRevoked] = useState<readonly string[]>([]);
  const remaining = rows.filter((row) => !revoked.includes(row.approval_id));

  return (
    <section aria-labelledby="attention">
      <h2 id="attention">Approvals needing attention</h2>
      <p>
        Each of these was granted and no longer authorizes a send. Nothing here can dispatch —
        the worker rechecks the same rules before it acts — so revoking is about closing the item
        out, not about stopping something in flight.
      </p>

      {remaining.length === 0 ? (
        <p>
          Nothing needs attention. Every approval that has been granted still authorizes the send
          it was granted for.
        </p>
      ) : (
        <ul aria-label="Stale approvals">
          {remaining.map((row) => (
            <StaleApproval
              key={row.approval_id}
              row={row}
              onRevoked={() => {
                setRevoked((closed) => [...closed, row.approval_id]);
              }}
            />
          ))}
        </ul>
      )}
    </section>
  );
}
