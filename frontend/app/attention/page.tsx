"use client";

import { useEffect, useState } from "react";

import { ApiRefused, listStaleApprovals } from "../../lib/api";
import type { AttentionRow } from "../../lib/api";
import { clearSessionToken } from "../../lib/session";
import { useSessionToken } from "../../lib/useSessionToken";
import { SignInForm } from "../SignInForm";
import { AttentionList } from "./AttentionList";

/**
 * The §7.5 attention page (T-068b).
 *
 * A page of its own rather than a panel on the review card, because the list is not about one
 * candidate. `T-068a`'s endpoint answers per campaign or across all of them, and an attention row
 * names a *revision* — including revisions the card has already moved past. Filtering it down to
 * whatever candidate a reviewer happens to be looking at would hide exactly the approvals nobody
 * is looking at, which are the ones this exists to surface.
 *
 * Loading, sign-in, and refusal handling mirror the review page deliberately (`T-151b`): a client
 * component because the bearer token lives in `sessionStorage` and a server render would fetch as
 * nobody; a `401` clears the token and shows the sign-in form; anything else is shown as the
 * backend's own sentence, because signing in again cannot fix a missing role.
 */
export default function AttentionPage() {
  const token = useSessionToken();
  const [rows, setRows] = useState<readonly AttentionRow[] | null>(null);
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    if (token === null) {
      return;
    }
    const controller = new AbortController();
    listStaleApprovals(token, controller.signal)
      .then((items) => {
        setRows(items);
        setRefused(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof ApiRefused && error.status === 401) {
          clearSessionToken();
          setRows(null);
          return;
        }
        setRefused(
          error instanceof ApiRefused
            ? error.detail
            : `Could not load the attention list: ${String(error)}`,
        );
      });
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

  if (refused !== null) {
    return (
      <main>
        <h1>Attention</h1>
        <p role="alert">{refused}</p>
      </main>
    );
  }

  if (rows === null) {
    return <main aria-busy="true">Loading approvals that need attention…</main>;
  }

  return (
    <main>
      <h1>Attention</h1>
      <AttentionList rows={rows} />
    </main>
  );
}
