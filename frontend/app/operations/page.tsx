"use client";

import { useEffect, useState } from "react";

import { ApiRefused, getOperationsOverview } from "../../lib/api";
import type { OperationsOverview } from "../../lib/api";
import { clearSessionToken } from "../../lib/session";
import { useSessionToken } from "../../lib/useSessionToken";
import { SignInForm } from "../SignInForm";
import { OperationsPanel } from "./OperationsPanel";

/**
 * The operations page (T-069c).
 *
 * Sign-in, `401`, and refusal handling mirror `/attention` and `/review` (`T-151b`). The `403`
 * case matters more here than anywhere else: this route is administrator-only (`VIEW_OPERATIONS`,
 * tier 5), so a reviewer who follows the link from the entry page will be refused, and telling
 * them to sign in again would send them round a loop that cannot help. The backend's own sentence
 * is shown instead.
 */
export default function OperationsPage() {
  const token = useSessionToken();
  const [overview, setOverview] = useState<OperationsOverview | null>(null);
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    if (token === null) {
      return;
    }
    const controller = new AbortController();
    getOperationsOverview(token, controller.signal)
      .then((loaded) => {
        setOverview(loaded);
        setRefused(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof ApiRefused && error.status === 401) {
          clearSessionToken();
          setOverview(null);
          return;
        }
        setRefused(
          error instanceof ApiRefused
            ? error.detail
            : `Could not load the operations panel: ${String(error)}`,
        );
      });
    return () => {
      controller.abort();
    };
  }, [token]);

  if (token === null) {
    return (
      <main>
        <h1>Operations</h1>
        <p>You are not signed in, so the operations panel cannot be shown.</p>
        <SignInForm />
      </main>
    );
  }

  if (refused !== null) {
    return (
      <main>
        <h1>Operations</h1>
        <p role="alert">{refused}</p>
      </main>
    );
  }

  if (overview === null) {
    return <main aria-busy="true">Loading the operations panel…</main>;
  }

  return (
    <main>
      <h1>Operations</h1>
      <OperationsPanel overview={overview} />
    </main>
  );
}
