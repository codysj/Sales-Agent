"use client";

import { use, useEffect, useState } from "react";

import { ApiRefused, getCandidateDetail } from "../../../lib/api";
import type { CandidateDetail } from "../../../lib/api";
import { clearSessionToken } from "../../../lib/session";
import { useSessionToken } from "../../../lib/useSessionToken";
import { SignInForm } from "../../SignInForm";
import { ReviewCard } from "../ReviewCard";

/**
 * One candidate's review page (T-064, T-151b; §12.3, §12.2).
 *
 * **A client component, and that is a change `T-151b` forced rather than a preference.** `T-064`
 * rendered this on the server, which was right while nothing was authenticated. It is not right
 * now: `T-151a` issues a bearer token and `lib/session.ts` keeps it in `sessionStorage`, which
 * exists only in the browser. A server render has no session and would fetch as nobody. The
 * alternative — putting the token in a cookie so the server could read it — is exactly the
 * exposure `T-065a` removed when it refused cookie authentication on mutations, so it is not an
 * alternative. `dynamic = "force-dynamic"` goes with it: there is no server render left to make
 * dynamic, and the data is fetched fresh on every mount regardless.
 *
 * **Signed out is a prompt, not an error.** A reviewer with no session sees the sign-in form on
 * the page they asked for and lands back on the card once they have one. A `401` from the backend
 * is treated the same way and clears the stored token first: a token the server has stopped
 * honouring is worse than none, because every later failure gets blamed on something else.
 *
 * **A `403` is not a `401`.** Signing in again cannot fix a missing role, and offering the form
 * would send a reviewer round a loop that can never succeed — so a refusal that is not `401` is
 * shown as what it is, with the backend's own sentence.
 *
 * **It refetches after every action that changes something** (`T-210`). It did not, and `T-071d`
 * watched what that costs: two runs of three saw the card claim a draft had been queued while the
 * section below it said none existed, and one saw revision 1 still displayed after saving
 * revision 2. Both are the same bug — the page fetched once and every later truth arrived
 * somewhere the card could not see. A counter in the dependency list rather than a cache library:
 * there is one query on this page, and the reviewer's own action is the only thing that
 * invalidates it.
 */
export default function ReviewPage({ params }: { params: Promise<{ candidateId: string }> }) {
  const { candidateId } = use(params);
  const token = useSessionToken();
  const [candidate, setCandidate] = useState<CandidateDetail | null>(null);
  const [refused, setRefused] = useState<string | null>(null);
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    if (token === null) {
      return;
    }
    const controller = new AbortController();
    getCandidateDetail(candidateId, token, controller.signal)
      .then((detail) => {
        setCandidate(detail);
        setRefused(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof ApiRefused && error.status === 401) {
          // Clearing the token is what signs the reviewer out: the hook re-reads the store and
          // the sign-in prompt renders. Nothing else has to be told.
          clearSessionToken();
          setCandidate(null);
          return;
        }
        setRefused(
          error instanceof ApiRefused
            ? error.detail
            : `Could not load this candidate: ${String(error)}`,
        );
      });
    return () => {
      controller.abort();
    };
  }, [candidateId, token, reloads]);

  if (token === null) {
    return (
      <main>
        <h1>Review</h1>
        <p>You are not signed in, so this candidate cannot be shown.</p>
        <SignInForm />
      </main>
    );
  }

  if (refused !== null) {
    return (
      <main>
        <h1>Review</h1>
        <p role="alert">{refused}</p>
      </main>
    );
  }

  if (candidate === null) {
    return <main aria-busy="true">Loading this candidate…</main>;
  }

  return (
    <main>
      <ReviewCard
        candidate={candidate}
        onChanged={() => {
          setReloads((count) => count + 1);
        }}
      />
    </main>
  );
}
