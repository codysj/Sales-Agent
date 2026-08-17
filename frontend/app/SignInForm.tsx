"use client";

import { useState } from "react";

import { ApiRefused, signIn } from "../lib/api";
import { setSessionToken } from "../lib/session";

/**
 * Signing in (T-151b; §12.2, §12.3).
 *
 * **There is no password field, and that is §12.2 rather than an omission.** The specification
 * says managed SSO/OIDC and "do not build custom password authentication"; `T-061b` wires the
 * real provider and is blocked on `Q-026`, which asks which provider and roster. Meanwhile
 * `T-151a`'s stub issues a session for a *known* local user and refuses itself outside `local`.
 * The form says so, because a reviewer typing their address into a box marked "sign in" should
 * know that nothing here checked anything.
 *
 * **It says it in their vocabulary, not this file's (`T-216`).** The paragraph ended "(T-061b)"
 * — a row in a backlog the reader has no access to, on the first screen they ever see, reading
 * as a fault code on a page whose job is to let somebody in. A rehearsal reader asked *"What is
 * T-061b?"* in the same breath as *"it says 'this verifies nothing' — is it safe to sign in?"*.
 * The identifier is gone and the honest part is stated as what it does rather than what it
 * lacks: checking no password and no directory is a fact a reader can act on, where "verifies
 * nothing" sounds like a warning about them.
 *
 * **A refusal is shown as the backend's own sentence.** "The development sign-in stub is refused
 * in production" and "no user with email …" are different problems with different fixes, and a
 * generic "sign-in failed" leaves a reviewer with nothing to do next. The 503 in particular is
 * the one worth reading: it means the dashboard is pointed at a backend where this cannot work,
 * which is a configuration answer rather than a typing mistake.
 *
 * **The token goes to `lib/session.ts` and nowhere else.** One place decides where a session
 * lives, so no component has to know.
 */
export function SignInForm({ onSignedIn }: { onSignedIn?: (token: string) => void }) {
  const [email, setEmail] = useState("");
  const [state, setState] = useState<"idle" | "signing-in">("idle");
  const [refused, setRefused] = useState<string | null>(null);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setState("signing-in");
    setRefused(null);
    try {
      const session = await signIn(email);
      if (session.token === null || session.token === undefined) {
        // The endpoint returns the token only on the response that creates the session, so an
        // absent one here means something answered `200` that was not a sign-in.
        setRefused("The server accepted the sign-in but returned no session token.");
        setState("idle");
        return;
      }
      setSessionToken(session.token);
      onSignedIn?.(session.token);
    } catch (error) {
      setRefused(
        error instanceof ApiRefused ? error.detail : `Could not reach the backend: ${String(error)}`,
      );
      setState("idle");
    }
  }

  return (
    <section aria-labelledby="sign-in">
      <h2 id="sign-in">Sign in</h2>
      <p>
        This is the local development sign-in. It checks no password and no directory — it issues
        a session for a user the backend already knows, and it refuses to run anywhere but a local
        environment. Managed single sign-on is not wired up yet.
      </p>

      <form
        onSubmit={(event) => {
          void submit(event);
        }}
        aria-label="Sign in"
      >
        <label htmlFor="sign-in-email">Email</label>
        <input
          id="sign-in-email"
          name="email"
          type="email"
          value={email}
          required
          autoComplete="username"
          onChange={(event) => {
            setEmail(event.target.value);
          }}
        />

        <button type="submit" disabled={state === "signing-in"}>
          {state === "signing-in" ? "Signing in…" : "Sign in"}
        </button>
      </form>

      {refused !== null && <p role="alert">{refused}</p>}
    </section>
  );
}
