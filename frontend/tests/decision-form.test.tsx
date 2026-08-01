// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DecisionForm } from "../app/review/DecisionForm";
import type { CandidateDetail, DecisionResponse } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * Rejecting and deferring from the card (T-066b2; §12.3 items 6 and 7, §10.6).
 *
 * §10.6 wants the reason structured so the feedback is analysable, and the failure worth testing
 * for is a decision recorded without one — or a deferral recorded with nothing to bring the
 * candidate back. Both are refused twice over, and these tests cover the near half; `T-066b1`'s
 * suite covers the server's.
 */

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "SYNTHETIC-session-token";

const CANDIDATE: CandidateDetail = {
  candidate_id: CANDIDATE_ID,
  campaign_id: "22222222-2222-4222-8222-222222222222",
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

function decision(overrides: Partial<DecisionResponse> = {}): DecisionResponse {
  return {
    decision_id: "33333333-3333-4333-8333-333333333333",
    candidate_id: CANDIDATE_ID,
    kind: "reject",
    category: "poor_buyer_role",
    notes: null,
    defer_until_date: null,
    defer_until_event: null,
    state: "rejected",
    record_version: "2026-07-31T11:00:00Z",
    ...overrides,
  };
}

function stubFetch(body: unknown, status = 200) {
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

function sentBody(stub: ReturnType<typeof stubFetch>): Record<string, unknown> {
  const body = stub.mock.calls[0]?.[1]?.body;
  if (typeof body !== "string") {
    throw new Error("the decision carried no JSON body");
  }
  return JSON.parse(body) as Record<string, unknown>;
}

function chooseCategory(value: string) {
  fireEvent.change(screen.getByLabelText("Why is this being rejected?"), { target: { value } });
}

function submitReject() {
  fireEvent.submit(screen.getByRole("form", { name: "Reject candidate" }));
}

function submitDefer() {
  fireEvent.submit(screen.getByRole("form", { name: "Defer candidate" }));
}

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: rejecting records the category the reviewer chose -------------------------------

describe("rejecting", () => {
  it("sends the category the reviewer picked", async () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("weak_or_stale_evidence");
    submitReject();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["category"]).toBe("weak_or_stale_evidence");
    expect(String(stub.mock.calls[0]?.[0])).toContain(`/candidates/${CANDIDATE_ID}/reject`);
  });

  it("offers §10.6's categories, minus the one that is a deferral", () => {
    // Ten, not eleven: `T-066a` refuses "defer until a date or event" as a *rejection* reason,
    // because a candidate rejected for waiting is one nobody will look at again. Offering it
    // would show a reviewer an option the server rejects.
    render(<DecisionForm candidate={CANDIDATE} />);

    const options = [
      ...screen.getByLabelText<HTMLSelectElement>("Why is this being rejected?").options,
    ].map((option) => option.value);

    expect(options).toContain("wrong_campaign");
    expect(options).toContain("compliance_or_suppression_concern");
    expect(options).not.toContain("defer_until_date_or_event");
    // Ten categories plus the empty "Select a reason".
    expect(options).toHaveLength(11);
  });

  it("labels each category in words rather than identifiers", () => {
    render(<DecisionForm candidate={CANDIDATE} />);

    const text = screen.getByLabelText("Why is this being rejected?").textContent ?? "";
    expect(text).toContain("Poor buyer role");
    expect(text).toContain("Weak or stale evidence");
    expect(text).not.toContain("poor_buyer_role");
  });

  it("sends optional notes when given, and null when not", async () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("wrong_campaign");
    fireEvent.change(screen.getByLabelText("Notes (optional)"), {
      target: { value: "SYNTHETIC: they moved to a different supplier." },
    });
    submitReject();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["notes"]).toBe("SYNTHETIC: they moved to a different supplier.");
  });

  it("sends null notes when the box is left empty", async () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("wrong_campaign");
    submitReject();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["notes"]).toBeNull();
  });

  it("shows the recorded category back in words", async () => {
    stubFetch(decision({ category: "poor_buyer_role", kind: "reject" }));
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("poor_buyer_role");
    submitReject();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("Poor buyer role");
    });
    expect(screen.getByRole("status").textContent).toContain("closed");
  });

  it("sends the record version the reviewer was shown", async () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("wrong_campaign");
    submitReject();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["record_version"]).toBe("2026-07-31T10:00:00Z");
  });
});

// --- criterion 2: a rejection cannot be submitted with no category --------------------------------

describe("the category requirement", () => {
  it("is required on the field itself", () => {
    render(<DecisionForm candidate={CANDIDATE} />);

    const select = screen.getByLabelText<HTMLSelectElement>("Why is this being rejected?");
    expect(select.required).toBe(true);
    expect(select.value).toBe("");
  });

  it("leaves Reject disabled until a category is chosen", () => {
    render(<DecisionForm candidate={CANDIDATE} />);

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Reject" }).disabled).toBe(true);

    chooseCategory("unsupported_claim");

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Reject" }).disabled).toBe(false);
  });

  it("sends nothing when submitted with no category", () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    submitReject();

    expect(stub).not.toHaveBeenCalled();
  });
});

// --- criterion 3: deferring captures a date or an event and shows it back --------------------------

describe("deferring", () => {
  it("sends a date", async () => {
    const stub = stubFetch(decision({ kind: "defer", state: "deferred" }));
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("Defer until a date"), {
      target: { value: "2026-12-01" },
    });
    submitDefer();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["until_date"]).toBe("2026-12-01");
    expect(String(stub.mock.calls[0]?.[0])).toContain(`/candidates/${CANDIDATE_ID}/defer`);
  });

  it("sends an event", async () => {
    // An event for "when they publish their storage roadmap", which has no date yet — genuinely
    // different from a date, which is why both are offered.
    const stub = stubFetch(decision({ kind: "defer", state: "deferred" }));
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("…or until an event"), {
      target: { value: "SYNTHETIC: when they publish their storage roadmap" },
    });
    submitDefer();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["until_event"]).toBe(
      "SYNTHETIC: when they publish their storage roadmap",
    );
  });

  it("leaves Defer disabled until there is a date or an event", () => {
    // A deferral with neither leaves review and nothing brings the candidate back.
    render(<DecisionForm candidate={CANDIDATE} />);

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Defer" }).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText("Defer until a date"), {
      target: { value: "2026-12-01" },
    });

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Defer" }).disabled).toBe(false);
  });

  it("does not treat whitespace as an event", () => {
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("…or until an event"), { target: { value: "   " } });

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Defer" }).disabled).toBe(true);
  });

  it("sends nothing when submitted with no waypoint", () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    submitDefer();

    expect(stub).not.toHaveBeenCalled();
  });

  it("shows the date it was deferred until", async () => {
    // A deferral confirmed as "done" tells nobody when it comes back.
    stubFetch(
      decision({
        kind: "defer",
        state: "deferred",
        category: "defer_until_date_or_event",
        defer_until_date: "2026-12-01",
      }),
    );
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("Defer until a date"), {
      target: { value: "2026-12-01" },
    });
    submitDefer();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("2026-12-01");
    });
    expect(screen.getByRole("status").textContent).toContain("Deferred until");
  });

  it("shows the event it was deferred until", async () => {
    stubFetch(
      decision({
        kind: "defer",
        state: "deferred",
        category: "product_not_ready",
        defer_until_event: "SYNTHETIC: when the pilot ships",
      }),
    );
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("…or until an event"), {
      target: { value: "SYNTHETIC: when the pilot ships" },
    });
    submitDefer();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("SYNTHETIC: when the pilot ships");
    });
    // A deferral may name a more specific reason than "not now", and it is the more useful row.
    expect(screen.getByRole("status").textContent).toContain("Product not ready");
  });

  it("defaults the category to §10.6's eleventh", async () => {
    const stub = stubFetch(decision({ kind: "defer", state: "deferred" }));
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("Defer until a date"), {
      target: { value: "2026-12-01" },
    });
    submitDefer();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["category"]).toBe("defer_until_date_or_event");
  });
});

// --- refusals ------------------------------------------------------------------------------------

describe("a refused decision", () => {
  it("shows the backend's own reason", async () => {
    stubFetch({ detail: "a deferral needs a date or an event to wait for" }, 409);
    render(<DecisionForm candidate={CANDIDATE} />);

    fireEvent.change(screen.getByLabelText("Defer until a date"), {
      target: { value: "2026-12-01" },
    });
    submitDefer();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("needs a date or an event");
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("refuses to send at all when there is no session", async () => {
    window.sessionStorage.clear();
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("wrong_campaign");
    submitReject();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("nothing was recorded");
  });

  it("sends the token as a bearer", async () => {
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("wrong_campaign");
    submitReject();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const headers = stub.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// --- T-155: requesting more research (ADR-022) ---------------------------------------------------

describe("requesting more research", () => {
  it("sends the category the reviewer picked", async () => {
    const stub = stubFetch(
      decision({ kind: "request_research", state: "review_pending", category: "weak_or_stale_evidence" }),
    );
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("weak_or_stale_evidence");
    fireEvent.click(screen.getByRole("button", { name: "Request more research" }));

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["category"]).toBe("weak_or_stale_evidence");
    expect(String(stub.mock.calls[0]?.[0])).toContain(
      `/candidates/${CANDIDATE_ID}/request-research`,
    );
  });

  it("never submits the rejection form", () => {
    // `type="button"`, not `type="submit"`. A reviewer asking for more evidence is not rejecting,
    // and sharing a form with the reject action is only safe if this cannot trigger it.
    const stub = stubFetch(decision());
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("weak_or_stale_evidence");
    fireEvent.click(screen.getByRole("button", { name: "Request more research" }));

    // Every call, not the first: `type="submit"` would fire the click *and* the submit, and
    // checking only `calls[0]` passed against exactly that mistake when it was controlled for.
    const paths = stub.mock.calls.map(([url]) => String(url));
    expect(paths.some((path) => path.includes("/reject"))).toBe(false);
    expect(paths).toHaveLength(1);
  });

  it("is disabled until a category is chosen", () => {
    // §10.6 structures this reason too: "why did somebody want more evidence here" is exactly the
    // evaluation data that list collects.
    render(<DecisionForm candidate={CANDIDATE} />);

    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Request more research" }).disabled,
    ).toBe(true);

    chooseCategory("weak_or_stale_evidence");

    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Request more research" }).disabled,
    ).toBe(false);
  });

  it("says the candidate stays in review", async () => {
    // ADR-022's decision, in the sentence a reviewer reads. The card does not vanish from their
    // queue, and telling them otherwise would be the one thing they would notice.
    stubFetch(
      decision({ kind: "request_research", state: "review_pending", category: "weak_or_stale_evidence" }),
    );
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("weak_or_stale_evidence");
    fireEvent.click(screen.getByRole("button", { name: "Request more research" }));

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("More research requested");
    });
    const status = screen.getByRole("status").textContent ?? "";
    expect(status).toContain("stays in review");
    expect(status).toContain("Weak or stale evidence");
  });

  it("shows the backend refusal when a pass is already in flight", async () => {
    // A reviewer who clicks twice wants one more pass, not two — and the reason is the backend's
    // sentence, not a generic failure.
    stubFetch(
      {
        detail:
          "a research pass for candidate 11111111-1111-4111-8111-111111111111 is already in " +
          "flight; a second request would duplicate the work rather than deepen it",
      },
      409,
    );
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("weak_or_stale_evidence");
    fireEvent.click(screen.getByRole("button", { name: "Request more research" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("already in flight");
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("sends the record version the reviewer was shown", async () => {
    const stub = stubFetch(decision({ kind: "request_research", state: "review_pending" }));
    render(<DecisionForm candidate={CANDIDATE} />);

    chooseCategory("wrong_campaign");
    fireEvent.click(screen.getByRole("button", { name: "Request more research" }));

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(sentBody(stub)["record_version"]).toBe("2026-07-31T10:00:00Z");
  });
});
