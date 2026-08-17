"use client";

import { useEffect, useState } from "react";

import { ApiRefused, listStaleApprovals, listStrandedRevisions } from "../../lib/api";
import type { AttentionRow, StrandedRevisionRow } from "../../lib/api";
import { clearSessionToken } from "../../lib/session";
import { useSessionToken } from "../../lib/useSessionToken";
import { SignInForm } from "../SignInForm";
import { AttentionList } from "./AttentionList";
import { StrandedRevisionList } from "./StrandedRevisionList";

/**
 * The §7.5 attention page (T-068b, T-209).
 *
 * A page of its own rather than a panel on the review card, because the lists are not about one
 * candidate. `T-068a`'s endpoint answers per campaign or across all of them, and an attention row
 * names a *revision* — including revisions the card has already moved past. Filtering it down to
 * whatever candidate a reviewer happens to be looking at would hide exactly the work nobody is
 * looking at, which is what this exists to surface.
 *
 * **Two lists, loaded independently** (`T-209`). §7.5 asks for stale approvals *and* invalidated
 * drafts, and they are separate endpoints. Sharing one loading state would let a refusal on
 * either one blank the other — and a page that hides work because a different query failed is the
 * exact failure this second list was added to end.
 *
 * Loading, sign-in, and refusal handling mirror the review page deliberately (`T-151b`): a client
 * component because the bearer token lives in `sessionStorage` and a server render would fetch as
 * nobody; a `401` clears the token and shows the sign-in form; anything else is shown as the
 * backend's own sentence, because signing in again cannot fix a missing role.
 */

/** Not-yet-loaded, loaded, or refused — three states, never conflated with an empty list. */
type Loaded<T> = { rows: readonly T[] } | { refused: string } | null;

export default function AttentionPage() {
  const token = useSessionToken();
  const [approvals, setApprovals] = useState<Loaded<AttentionRow>>(null);
  const [stranded, setStranded] = useState<Loaded<StrandedRevisionRow>>(null);

  useEffect(() => {
    if (token === null) {
      return;
    }
    const controller = new AbortController();

    function load<T>(
      request: Promise<T[]>,
      setter: (value: Loaded<T>) => void,
      what: string,
    ): void {
      request
        .then((rows) => {
          setter({ rows });
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) {
            return;
          }
          if (error instanceof ApiRefused && error.status === 401) {
            clearSessionToken();
            setter(null);
            return;
          }
          setter({
            refused:
              error instanceof ApiRefused
                ? error.detail
                : `Could not load ${what}: ${String(error)}`,
          });
        });
    }

    load(listStaleApprovals(token, controller.signal), setApprovals, "the attention list");
    load(listStrandedRevisions(token, controller.signal), setStranded, "the stuck drafts");

    return () => {
      controller.abort();
    };
  }, [token]);

  if (token === null) {
    return (
      <main>
        <h1>Attention</h1>
        <p>You are not signed in, so stale approvals cannot be shown.</p>
        <SignInForm />
      </main>
    );
  }

  if (approvals === null && stranded === null) {
    return <main aria-busy="true">Loading the work that needs attention…</main>;
  }

  return (
    <main>
      <h1>Attention</h1>
      {approvals === null ? null : "refused" in approvals ? (
        <p role="alert">{approvals.refused}</p>
      ) : (
        <AttentionList rows={approvals.rows} />
      )}
      {stranded === null ? null : "refused" in stranded ? (
        <p role="alert">{stranded.refused}</p>
      ) : (
        <StrandedRevisionList rows={stranded.rows} />
      )}
    </main>
  );
}
