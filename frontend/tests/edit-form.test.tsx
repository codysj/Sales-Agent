// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { EditForm } from "../app/review/EditForm";
import { CHECK_EXPLANATIONS } from "../app/review/EditForm";
import type { CandidateDetail, EditResponse } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * The editing form (T-065b; §12.3 items 5–7, §10.5).
 *
 * Rendered into `jsdom` rather than with `renderToStaticMarkup`, because unlike `T-064`'s card
 * this component has behaviour: a submit, a request, and three outcomes. ADR-021 said nothing was
 * added before a screen needed it, and this is the screen — `jsdom` and `@testing-library/react`
 * arrived here and nowhere earlier. The environment is set per file, so the other suites keep
 * running in `node`.
 *
 * `fetch` is stubbed, not mocked at the module boundary: the point of several of these is that
 * `lib/api.ts` sends the right method, the right body, and the `Authorization` header
 * `T-065a` requires — assertions that a mocked `editRevision` would erase.
 */

const REVISION: NonNullable<CandidateDetail["current_revision"]> = {
  revision_id: "55555555-5555-4555-8555-555555555555",
  revision_number: 1,
  subject: "SYNTHETIC subject line",
  body: "SYNTHETIC body paragraph.",
  state: "review_pending",
  approved_claim_ids: [],
  evidence_ids: [],
  content_hash: "a".repeat(64),
  record_version: "2026-07-31T10:00:00Z",
};

function response(overrides: Partial<EditResponse> = {}): EditResponse {
  return {
    revision: { ...REVISION, revision_id: "66666666-6666-4666-8666-666666666666", revision_number: 2 },
    superseded_revision_id: REVISION.revision_id,
    revoked_approvals: [],
    expired_approvals: [],
    is_valid: true,
    failed_checks: [],
    ...overrides,
  };
}

/** A `fetch` that answers once with ``body`` at ``status``, and records what it was called with. */
function stubFetch(body: unknown, status = 200) {
  // Typed parameters, so `mock.calls[0][1]` is the `RequestInit` rather than an empty tuple —
  // several tests below assert on exactly what `lib/api.ts` put on the wire.
  const stub = vi.fn<(url: URL | string, init?: RequestInit) => Promise<Response>>(() =>
    Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      json: () => Promise.resolve(body),
    } as Response),
  );
  vi.stubGlobal("fetch", stub);
  return stub;
}

/** What `lib/api.ts` actually put on the wire. */
function sentBody(stub: ReturnType<typeof stubFetch>): Record<string, unknown> {
  const init = stub.mock.calls[0]?.[1];
  const body = init?.body;
  if (typeof body !== "string") {
    throw new Error("the request carried no JSON body");
  }
  return JSON.parse(body) as Record<string, unknown>;
}

function fillIn(reason = "Tone or wording") {
  fireEvent.change(screen.getByLabelText("Why is this being corrected?"), {
    target: { value: reason },
  });
}

function submit() {
  fireEvent.submit(screen.getByRole("form", { name: "Edit draft" }));
}

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, "SYNTHETIC-session-token");
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: submitting shows revision N+1 and marks the previous one superseded ------------

describe("a successful edit", () => {
  it("shows the new revision number and says the previous one is superseded", async () => {
    stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
    });
    const status = screen.getByRole("status").textContent ?? "";
    expect(status).toContain("Saved as revision 2");
    expect(status).toContain("Revision 1 is superseded");
    expect(status).toContain("can no longer be approved");
  });

  it("reports the approval the edit retired", async () => {
    // §10.5: editing an approved message invalidates the prior approval. A reviewer who is not
    // told that will assume the approval carried across to the text they just wrote.
    stubFetch(response({ revoked_approvals: ["77777777-7777-4777-8777-777777777777"] }));
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("One approval");
    });
    expect(screen.getByRole("status").textContent).toContain("was retired");
  });

  it("counts a revoked and an expired approval together", async () => {
    stubFetch(
      response({
        revoked_approvals: ["77777777-7777-4777-8777-777777777777"],
        expired_approvals: ["88888888-8888-4888-8888-888888888888"],
      }),
    );
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("2 approvals");
    });
    expect(screen.getByRole("status").textContent).toContain("were retired");
  });

  it("says nothing about approvals when none were retired", async () => {
    stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("status")).toBeTruthy();
    });
    expect(screen.getByRole("status").textContent).not.toContain("retired");
  });

  it("says validation passed when it did", async () => {
    stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("Validation passed");
    });
  });
});

// --- criterion 2: a validation failure names its specific check ----------------------------------

describe("a validation failure", () => {
  it("names the check that failed, not a generic error", async () => {
    stubFetch(
      response({ is_valid: false, failed_checks: ["claim_citations"], revision: { ...REVISION, revision_number: 2, state: "validation_failed" } }),
    );
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByLabelText("Failed validation checks")).toBeTruthy();
    });
    const checks = screen.getByLabelText("Failed validation checks").textContent ?? "";
    expect(checks).toContain("claim_citations");
    expect(checks).toContain("cites a claim that is not approved");
  });

  it("lists every failed check", async () => {
    stubFetch(
      response({
        is_valid: false,
        failed_checks: ["claim_citations", "product_readiness", "compliance_elements"],
        revision: { ...REVISION, revision_number: 2, state: "validation_failed" },
      }),
    );
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getAllByRole("listitem")).toHaveLength(3);
    });
  });

  it("says the edit was saved, because it was", async () => {
    // The revision exists in `validation_failed`. A reviewer told only "failed" would reasonably
    // believe their text was discarded and retype it.
    stubFetch(
      response({ is_valid: false, failed_checks: ["suppression"], revision: { ...REVISION, revision_number: 2, state: "validation_failed" } }),
    );
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("Saved, but validation failed");
    });
    const alert = screen.getByRole("alert").textContent ?? "";
    expect(alert).toContain("validation_failed");
    expect(alert).toContain("nothing you wrote was lost");
  });

  it("shows an unrecognised check by its identifier rather than swallowing it", async () => {
    stubFetch(
      response({ is_valid: false, failed_checks: ["a_check_added_after_this_map"], revision: { ...REVISION, revision_number: 2, state: "validation_failed" } }),
    );
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByLabelText("Failed validation checks").textContent).toContain(
        "a_check_added_after_this_map",
      );
    });
  });

  it("keeps the identifier in every explanation", () => {
    // A reviewer reads the sentence; whoever they escalate to searches the identifier. An
    // explanation that dropped its key would break the second use.
    for (const [check, explanation] of Object.entries(CHECK_EXPLANATIONS)) {
      expect(explanation).toContain(check);
    }
  });
});

// --- criterion 3: no submission without a correction reason --------------------------------------

describe("the correction reason", () => {
  it("is required on the field itself", () => {
    // §12.3 item 7, enforced by the browser before any request leaves — with `T-065a`'s own
    // refusal behind it as the guard that actually binds.
    render(<EditForm revision={REVISION} />);

    const select = screen.getByLabelText<HTMLSelectElement>("Why is this being corrected?");
    expect(select.required).toBe(true);
    expect(select.value).toBe("");
  });

  it("offers §12.3's structured reasons rather than a free-text box", () => {
    render(<EditForm revision={REVISION} />);

    const select = screen.getByLabelText<HTMLSelectElement>("Why is this being corrected?");
    expect(select.tagName).toBe("SELECT");
    expect([...select.options].map((option) => option.value)).toContain("Tone or wording");
  });

  it("is sent with the edit", async () => {
    const stub = stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn("Evidence does not support the claim");
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const body = sentBody(stub);
    expect(body["correction_reason"]).toBe("Evidence does not support the claim");
  });
});

// --- what the request carries --------------------------------------------------------------------

describe("the request", () => {
  it("sends the session token as a bearer, never as a cookie", async () => {
    // `T-065a` refuses cookie authentication on mutations until `T-070` adds CSRF. A form that
    // relied on the browser attaching credentials would be the exposure that refusal removes.
    const stub = stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const init = stub.mock.calls[0]?.[1] as RequestInit;
    expect(init.method).toBe("POST");
    expect((init.headers as Record<string, string>)["authorization"]).toBe(
      "Bearer SYNTHETIC-session-token",
    );
    expect(init.credentials).toBeUndefined();
  });

  it("sends the record version the reviewer was shown", async () => {
    // Optimistic concurrency: if the revision moved since the card rendered, `T-065a` answers 409
    // rather than applying the edit to text nobody read.
    const stub = stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const body = sentBody(stub);
    expect(body["record_version"]).toBe("2026-07-31T10:00:00Z");
  });

  it("posts to the revision's own edit path", async () => {
    const stub = stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(String(stub.mock.calls[0]?.[0])).toContain(`/api/review/revisions/${REVISION.revision_id}/edit`);
  });
});

// --- refusals ------------------------------------------------------------------------------------

describe("a refused edit", () => {
  it("shows the backend's own reason, not a generic failure", async () => {
    stubFetch(
      { detail: "this revision changed since it was loaded; reload the card before editing" },
      409,
    );
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("changed since it was loaded");
    });
  });

  it("refuses to send at all when there is no session", async () => {
    // `T-151` is the sign-in screen. Until it lands there is no token in a real browser, and
    // saying so beats posting an unauthenticated request and rendering whatever 401 comes back.
    window.sessionStorage.clear();
    const stub = stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("nothing was changed");
  });

  it("leaves no success message behind", async () => {
    stubFetch({ detail: "no such revision" }, 404);
    render(<EditForm revision={REVISION} />);

    fillIn();
    submit();

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

// --- the form itself -----------------------------------------------------------------------------

describe("the form", () => {
  it("starts from the current text so an edit is a change, not a retype", () => {
    render(<EditForm revision={REVISION} />);

    expect(screen.getByLabelText<HTMLInputElement>("Subject").value).toBe(
      "SYNTHETIC subject line",
    );
    expect(screen.getByLabelText<HTMLTextAreaElement>("Body").value).toBe(
      "SYNTHETIC body paragraph.",
    );
  });

  it("says what editing will do before it is done", () => {
    render(<EditForm revision={REVISION} />);

    const text = screen.getByRole("form", { name: "Edit draft" }).parentElement?.textContent ?? "";
    expect(text).toContain("creates revision 2");
    expect(text).toContain("supersedes this one");
  });

  it("sends what the reviewer typed, not what was loaded", async () => {
    const stub = stubFetch(response());
    render(<EditForm revision={REVISION} />);

    fireEvent.change(screen.getByLabelText("Subject"), {
      target: { value: "SYNTHETIC edited subject" },
    });
    fillIn();
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const body = sentBody(stub);
    expect(body["subject"]).toBe("SYNTHETIC edited subject");
  });
});
