// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Suspense } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ReviewPage from "../app/review/[candidateId]/page";
import { SignInForm } from "../app/SignInForm";
import SignInPage from "../app/sign-in/page";
import { SESSION_TOKEN_KEY, getSessionToken, setSessionToken } from "../lib/session";

/**
 * Signing in, and what every page does when nobody has (T-151b; §12.2, §12.3).
 *
 * The three criteria are about a reviewer's experience of *not being signed in*, which is the
 * state the dashboard was previously unable to represent at all: `T-064`'s page fetched as nobody
 * and would have rendered whatever a `401` produced.
 *
 * `fetch` is stubbed per test with a small router keyed on method and path, rather than one
 * canned response. Signing in and then reading a candidate are two different calls, and a stub
 * that answered both identically would let a test pass while the page called the wrong one.
 */

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "SYNTHETIC-session-token";

const SESSION = {
  user_id: "22222222-2222-4222-8222-222222222222",
  email: "synthetic.reviewer@example.com",
  display_name: "SYNTHETIC Reviewer",
  roles: ["operator_reviewer"],
  expires_at: "2026-07-31T18:00:00Z",
  issued_via: "stub",
  token: null as string | null,
};

const CANDIDATE = {
  candidate_id: CANDIDATE_ID,
  campaign_id: "33333333-3333-4333-8333-333333333333",
  campaign_name: "SYNTHETIC-Campaign",
  account_name: "SYNTHETIC-Account-Alpha",
  account_domain: "alpha.example.com",
  contact_name: "SYNTHETIC Person Alpha",
  contact_role: null,
  contact_points: [],
  state: "review_pending",
  opportunity_type: null,
  evidence: [],
  product_name: "SYNTHETIC-Product",
  product_readiness: null,
  product_readiness_summary: null,
  approved_claims: [],
  suppression: { contact_suppressed: false, account_suppressed: false },
  crm_relationship: null,
  current_revision: null,
  what_happens_next: "Nothing is sent.",
  record_version: "2026-07-31T10:00:00Z",
};

type Answer = { status: number; body: unknown };

/** A `fetch` that answers by method and path prefix. Unrouted calls fail loudly. */
function route(answers: Record<string, Answer>) {
  const stub = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(
    (url, init) => {
      const method = (init?.method ?? "GET").toUpperCase();
      const path = new URL(String(url)).pathname;
      const key = Object.keys(answers).find((each) => {
        const [wantedMethod, wantedPath] = each.split(" ");
        return wantedMethod === method && path.startsWith(String(wantedPath));
      });
      if (key === undefined) {
        throw new Error(`no stubbed answer for ${method} ${path}`);
      }
      const answer = answers[key] as Answer;
      return Promise.resolve({
        ok: answer.status >= 200 && answer.status < 300,
        status: answer.status,
        json: () => Promise.resolve(answer.body),
      } as Response);
    },
  );
  vi.stubGlobal("fetch", stub);
  return stub;
}

/**
 * Route params, as an already-settled thenable.
 *
 * Next hands a client page its params as a promise and `use()` unwraps it. A bare
 * `Promise.resolve` would make React suspend on first render and resume on a later tick, so every
 * assertion here would be racing a mechanism none of these tests are about. React reads a
 * thenable that already carries `status` and `value` synchronously — which is the state the
 * promise is in by the time a real navigation has happened, and it keeps the tests about
 * authentication.
 */
const params = Object.assign(Promise.resolve({ candidateId: CANDIDATE_ID }), {
  status: "fulfilled" as const,
  value: { candidateId: CANDIDATE_ID },
});

function renderReviewPage() {
  // The `Suspense` boundary mirrors the one Next gives every route segment.
  return render(
    <Suspense fallback={<p>Loading…</p>}>
      <ReviewPage params={params} />
    </Suspense>,
  );
}

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: signing in produces a session the review page uses -----------------------------

describe("signing in", () => {
  it("stores the token the backend issued", async () => {
    route({ "POST /api/auth/stub-sign-in": { status: 200, body: { ...SESSION, token: TOKEN } } });
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: SESSION.email } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(getSessionToken()).toBe(TOKEN);
    });
  });

  it("sends the email and nothing resembling a password", async () => {
    // §12.2: no custom password authentication. A field the form does not have is a field nobody
    // can be asked to type into a box that verifies nothing.
    const stub = route({
      "POST /api/auth/stub-sign-in": { status: 200, body: { ...SESSION, token: TOKEN } },
    });
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: SESSION.email } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const body = stub.mock.calls[0]?.[1]?.body;
    if (typeof body !== "string") {
      throw new Error("the sign-in request carried no JSON body");
    }
    expect(JSON.parse(body)).toEqual({ email: SESSION.email });
    expect(screen.queryByLabelText("Password")).toBeNull();
  });

  it("says the sign-in verifies nothing", () => {
    render(<SignInForm />);

    const text = screen.getByRole("form", { name: "Sign in" }).parentElement?.textContent ?? "";
    expect(text).toContain("verifies nothing");
    expect(text).toContain("T-061b");
  });

  it("takes the review page from signed out to showing the candidate", async () => {
    // The criterion end to end: no token, sign in on the page itself, and the card appears —
    // without a reload, because the token is an external store every component re-reads.
    route({
      "POST /api/auth/stub-sign-in": { status: 200, body: { ...SESSION, token: TOKEN } },
      "GET /api/review/candidates": { status: 200, body: CANDIDATE },
    });
    renderReviewPage();

    expect(screen.getByText(/not signed in/)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: SESSION.email } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Candidate review card")).toBeTruthy();
    });
    expect(screen.getByText(/SYNTHETIC-Account-Alpha/)).toBeTruthy();
  });

  it("sends the token as a bearer when reading a candidate", async () => {
    const stub = route({ "GET /api/review/candidates": { status: 200, body: CANDIDATE } });
    setSessionToken(TOKEN);
    renderReviewPage();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const headers = stub.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// --- criterion 2: a signed-out reviewer sees a prompt, not a 401 or a blank card ------------------

describe("signed out", () => {
  it("prompts on the review page instead of fetching", async () => {
    const stub = route({});
    renderReviewPage();

    expect(await screen.findByRole("form", { name: "Sign in" })).toBeTruthy();
    expect(screen.getByText(/not signed in/)).toBeTruthy();
    expect(stub).not.toHaveBeenCalled();
  });

  it("prompts on the sign-in page", () => {
    route({});
    render(<SignInPage />);

    expect(screen.getByRole("form", { name: "Sign in" })).toBeTruthy();
  });

  it("shows the prompt again when the backend rejects a stored token", async () => {
    // A token that has expired or been revoked. The page must not sit on a spinner or blame the
    // candidate for a session problem.
    route({ "GET /api/review/candidates": { status: 401, body: { detail: "no session" } } });
    setSessionToken(TOKEN);
    renderReviewPage();

    await waitFor(() => {
      expect(screen.getByRole("form", { name: "Sign in" })).toBeTruthy();
    });
  });

  it("forgets a token the backend has stopped honouring", async () => {
    // Keeping it would make every later request fail for a reason the dashboard attributes to
    // something else.
    route({ "GET /api/review/candidates": { status: 401, body: { detail: "no session" } } });
    setSessionToken(TOKEN);
    renderReviewPage();

    await waitFor(() => {
      expect(getSessionToken()).toBeNull();
    });
    expect(window.sessionStorage.getItem(SESSION_TOKEN_KEY)).toBeNull();
  });

  it("does not offer the form for a 403, which signing in again cannot fix", async () => {
    // A missing role is not a missing session. Offering sign-in would send a reviewer round a
    // loop that can never succeed.
    route({
      "GET /api/review/candidates": {
        status: 403,
        body: { detail: "this action requires view_review_queue" },
      },
    });
    setSessionToken(TOKEN);
    renderReviewPage();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("view_review_queue");
    });
    expect(screen.queryByRole("form", { name: "Sign in" })).toBeNull();
    expect(getSessionToken()).toBe(TOKEN);
  });

  it("clears a token the session endpoint no longer recognises", async () => {
    route({ "GET /api/auth/session": { status: 401, body: { detail: "no session" } } });
    setSessionToken(TOKEN);
    render(<SignInPage />);

    await waitFor(() => {
      expect(screen.getByRole("form", { name: "Sign in" })).toBeTruthy();
    });
    expect(getSessionToken()).toBeNull();
  });
});

// --- criterion 3: a rejected sign-in shows the backend's reason ----------------------------------

describe("a rejected sign-in", () => {
  it("shows the refusal for a backend where the stub is not allowed", async () => {
    // The 503 is the one worth reading: it means the dashboard is pointed at a backend where this
    // cannot work, which is a configuration answer rather than a typing mistake.
    const detail =
      "the development sign-in stub is refused in production; it verifies nothing and exists " +
      "only for local development.";
    route({ "POST /api/auth/stub-sign-in": { status: 503, body: { detail } } });
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: SESSION.email } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("refused in production");
    });
  });

  it("shows the refusal for an unknown user", async () => {
    route({
      "POST /api/auth/stub-sign-in": {
        status: 404,
        body: { detail: "no user with email 'nobody@example.com'; the stub signs in an existing user" },
      },
    });
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nobody@example.com" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("no user with email");
    });
  });

  it("stores no token when the sign-in was refused", async () => {
    route({ "POST /api/auth/stub-sign-in": { status: 404, body: { detail: "no such user" } } });
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nobody@example.com" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    expect(getSessionToken()).toBeNull();
  });

  it("says the backend was unreachable rather than blaming the reviewer", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: SESSION.email } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("Could not reach the backend");
    });
  });

  it("lets the reviewer try again after a refusal", async () => {
    route({ "POST /api/auth/stub-sign-in": { status: 404, body: { detail: "no such user" } } });
    render(<SignInForm />);

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "nobody@example.com" } });
    fireEvent.submit(screen.getByRole("form", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    // Not left disabled: a form that refuses once and then refuses to be used again is worse
    // than the refusal.
    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Sign in" }).disabled).toBe(false);
  });
});

// --- the signed-in state, and signing out ---------------------------------------------------------

describe("signed in", () => {
  it("shows who you are and what the session is", async () => {
    route({ "GET /api/auth/session": { status: 200, body: SESSION } });
    setSessionToken(TOKEN);
    render(<SignInPage />);

    await waitFor(() => {
      expect(screen.getByText(/SYNTHETIC Reviewer/)).toBeTruthy();
    });
    const text = document.body.textContent ?? "";
    expect(text).toContain("operator_reviewer");
    // A stub session is labelled as one: §17.5 wants a development session distinguishable at a
    // glance, and the dashboard is where a reviewer would see it.
    expect(text).toContain("verified nothing");
  });

  it("says plainly when a session holds no roles", async () => {
    route({ "GET /api/auth/session": { status: 200, body: { ...SESSION, roles: [] } } });
    setSessionToken(TOKEN);
    render(<SignInPage />);

    await waitFor(() => {
      expect(screen.getByText(/review nothing/)).toBeTruthy();
    });
  });

  it("revokes server-side before forgetting the token", async () => {
    const stub = route({
      "GET /api/auth/session": { status: 200, body: SESSION },
      "DELETE /api/auth/session": { status: 204, body: null },
    });
    setSessionToken(TOKEN);
    render(<SignInPage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(getSessionToken()).toBeNull();
    });
    const deletes = stub.mock.calls.filter(([, init]) => init?.method === "DELETE");
    expect(deletes).toHaveLength(1);
  });

  it("keeps the token when signing out could not reach the backend", async () => {
    // Clearing first would leave a live session nobody holds — usable by anyone who copied the
    // token, and invisible to the person who thought they had signed out.
    route({
      "GET /api/auth/session": { status: 200, body: SESSION },
      "DELETE /api/auth/session": { status: 500, body: { detail: "boom" } },
    });
    setSessionToken(TOKEN);
    render(<SignInPage />);
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Sign out" })).toBeTruthy();
    });

    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    expect(getSessionToken()).toBe(TOKEN);
  });
});
