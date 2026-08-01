"use client";

import { useEffect, useState } from "react";

import { ApiRefused, listCandidateQueue, listRevisionQueue } from "../../lib/api";
import type { CandidatePage, RevisionPage } from "../../lib/api";
import { clearSessionToken } from "../../lib/session";
import { useSessionToken } from "../../lib/useSessionToken";
import { SignInForm } from "../SignInForm";
import { ReviewQueue } from "./ReviewQueue";

/**
 * The review queue page (T-160).
 *
 * A static segment beside `[candidateId]`, so `/review` is the list and `/review/<id>` is the
 * card. Next resolves the static segment first, which is why this does not collide with a
 * candidate whose id happened to be the string "review" — ids are UUIDs, and the router would
 * prefer this file regardless.
 *
 * **Both queues load together and fail together.** They answer one question — what is waiting —
 * and a screen that showed candidates while silently omitting revisions because the second
 * request failed would be worse than one that says it could not load: the reviewer would work
 * the half they can see and never learn the other half exists. `Promise.all` rejects on the first
 * failure, and the refusal is shown whole.
 *
 * Sign-in, `401`, and refusal handling mirror `/attention` and the review card (`T-151b`): a
 * client component because the bearer token lives in `sessionStorage`; a `401` clears the token
 * and shows the form; anything else is the backend's own sentence, because signing in again
 * cannot fix a missing role.
 */
export default function ReviewQueuePage() {
  const token = useSessionToken();
  const [queues, setQueues] = useState<{ candidates: CandidatePage; revisions: RevisionPage } | null>(
    null,
  );
  const [refused, setRefused] = useState<string | null>(null);

  useEffect(() => {
    if (token === null) {
      return;
    }
    const controller = new AbortController();
    Promise.all([
      listCandidateQueue(token, controller.signal),
      listRevisionQueue(token, controller.signal),
    ])
      .then(([candidates, revisions]) => {
        setQueues({ candidates, revisions });
        setRefused(null);
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (error instanceof ApiRefused && error.status === 401) {
          clearSessionToken();
          setQueues(null);
          return;
        }
        setRefused(
          error instanceof ApiRefused
            ? error.detail
            : `Could not load the review queue: ${String(error)}`,
        );
      });
    return () => {
      controller.abort();
    };
  }, [token]);

  if (token === null) {
    return (
      <main>
        <h1>Review queue</h1>
        <p>You are not signed in, so the review queue cannot be shown.</p>
        <SignInForm />
      </main>
    );
  }

  if (refused !== null) {
    return (
      <main>
        <h1>Review queue</h1>
        <p role="alert">{refused}</p>
      </main>
    );
  }

  if (queues === null) {
    return <main aria-busy="true">Loading the review queue…</main>;
  }

  return (
    <main>
      <h1>Review queue</h1>
      <ReviewQueue
        candidates={queues.candidates.rows}
        candidateTotal={queues.candidates.total}
        revisions={queues.revisions.rows}
        revisionTotal={queues.revisions.total}
      />
    </main>
  );
}
