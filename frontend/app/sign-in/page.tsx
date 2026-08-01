"use client";

import { useEffect, useState } from "react";

import { ApiRefused, getSession, signOut } from "../../lib/api";
import type { SessionInfo } from "../../lib/api";
import { clearSessionToken, getSessionToken } from "../../lib/session";
import { useSessionToken } from "../../lib/useSessionToken";
import { SignInForm } from "../SignInForm";

/**
 * The sign-in page (T-151b; §12.2).
 *
 * A route of its own, because otherwise the only way to obtain a session would be to guess a
 * candidate URL and be refused on it — which works, but is not something to hand a reviewer.
 *
 * **It asks the backend who you are rather than trusting the stored token.** A token in
 * `sessionStorage` proves only that a sign-in happened at some point; it may have expired
 * (`T-061a` gives eight hours) or been revoked from another device. `GET /api/auth/session`
 * answers with the session the server will actually honour, and a `null` answer clears the token
 * here so the reviewer is told to sign in instead of discovering it one failed request later.
 *
 * **Signing out revokes server-side, then forgets locally, in that order.** Clearing first and
 * failing to reach the backend would leave a live session nobody holds — usable by anyone who had
 * copied the token, and invisible to the person who thought they had signed out.
 */
export default function SignInPage() {
  const token = useSessionToken();
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  useEffect(() => {
    if (token === null) {
      // Nothing to check, and nothing to record: "signed out" is what having no token *is*, so
      // it is derived below rather than stored. State set from a value already in scope during
      // render is a second copy that can disagree with the first.
      return;
    }
    const controller = new AbortController();
    getSession(token, controller.signal)
      .then((live) => {
        if (live === null) {
          // Expired or revoked. Clearing it re-runs this through the hook and lands on the form.
          clearSessionToken();
        }
        setSession(live);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setProblem(
          error instanceof ApiRefused
            ? error.detail
            : `Could not reach the backend: ${String(error)}`,
        );
      });
    return () => {
      controller.abort();
    };
  }, [token]);

  async function endSession() {
    const token = getSessionToken();
    if (token === null) {
      setSession(null);
      return;
    }
    try {
      await signOut(token);
    } catch (error) {
      setProblem(
        error instanceof ApiRefused
          ? error.detail
          : `Could not reach the backend to sign out: ${String(error)}`,
      );
      return;
    }
    clearSessionToken();
    setSession(null);
  }

  return (
    <main>
      <h1>Matrix Power — review dashboard</h1>

      {problem !== null && <p role="alert">{problem}</p>}

      {token !== null && session === null && problem === null && (
        <p aria-busy="true">Checking your session…</p>
      )}

      {token === null && <SignInForm />}

      {session !== null && (
        <section aria-labelledby="signed-in">
          <h2 id="signed-in">Signed in</h2>
          <dl>
            <dt>You are</dt>
            <dd>
              {session.display_name} ({session.email})
            </dd>
            <dt>Roles</dt>
            <dd>{session.roles.length === 0 ? "None. You can sign in but review nothing." : session.roles.join(", ")}</dd>
            <dt>Session expires</dt>
            <dd>
              <time dateTime={session.expires_at}>
                {new Date(session.expires_at).toISOString().replace("T", " ").slice(0, 16)} UTC
              </time>
            </dd>
            <dt>Issued via</dt>
            <dd>
              {session.issued_via === "stub"
                ? "stub — local development sign-in, which verified nothing"
                : session.issued_via}
            </dd>
          </dl>
          <button
            type="button"
            onClick={() => {
              void endSession();
            }}
          >
            Sign out
          </button>
        </section>
      )}
    </main>
  );
}
