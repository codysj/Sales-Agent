// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { OperationsPanel } from "../app/operations/OperationsPanel";
import type { OperationsOverview } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * The operations panel (T-069c; §17.5, §17.6).
 *
 * Three things an operator holding a pager is trusting, and the tests are about those rather than
 * about markup: that **shadow mode is the first thing they read**, that a dead job tells them
 * *why* it died rather than only that it did, and that a switch carries the reason they typed —
 * and shows the backend's own refusal when it is refused.
 */

const TOKEN = "SYNTHETIC-session-token";

const OVERVIEW: OperationsOverview = {
  shadow_mode: true,
  flags_in_force: [],
  jobs_by_state: { queued: 3, dead: 1 },
  oldest_queued_job_age_seconds: 7200,
  dead_jobs: 1,
  dead_job_sample: [
    {
      job_id: "11111111-1111-4111-8111-111111111111",
      job_type: "research.capture_evidence",
      reason: "SYNTHETIC permanent failure: the fixture source returned nothing",
      attempt_count: 5,
      requires_human_review: true,
    },
  ],
  outbox_pending: 2,
  oldest_pending_outbox_age_seconds: 45,
  delivery_ambiguous_threads: 0,
  candidates_awaiting_review: 4,
  revisions_awaiting_review: 2,
  oldest_review_item_age_seconds: null,
  claim_invalidations: 1,
  suppressed_send_attempts: 3,
  not_measured: [],
};

function panel(overrides: Partial<OperationsOverview> = {}) {
  return <OperationsPanel overview={{ ...OVERVIEW, ...overrides }} />;
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

function changed(key: string, enabled: boolean, shadowMode = true) {
  return {
    key,
    enabled,
    reason: "SYNTHETIC",
    set_by: "admin-1",
    set_at: "2026-07-31T10:00:00Z",
    shadow_mode: shadowMode,
    what_happens_next: "Live sending stays gated (G-07).",
  };
}

function type(key: string, reason: string) {
  fireEvent.change(screen.getByLabelText("Why are you doing this?", { selector: `#reason-${key}` }), {
    target: { value: reason },
  });
}

function submit(name: string) {
  fireEvent.submit(screen.getByRole("form", { name }));
}

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: shadow mode is the first thing on the panel ------------------------------------

describe("the safety posture", () => {
  it("is the first section on the page", () => {
    // Asserted by position, not merely by presence: an operator opening this during an incident
    // is asking one question before any other, and a row buried in a table answers it only to
    // somebody who already knew to look.
    render(panel());

    const headings = screen.getAllByRole("heading", { level: 2 });
    expect(headings[0]?.textContent).toBe("Safety posture");
  });

  it("states plainly that nothing can leave when shadow mode is on", () => {
    render(panel({ shadow_mode: true }));

    expect(screen.getByRole("status").textContent).toContain("Shadow mode is ON");
    expect(screen.getByRole("status").textContent).toContain("No external effect can happen");
  });

  it("says so when shadow mode is off, and names the gate that still applies", () => {
    // The dangerous reading is "off means sending". It does not: G-07 governs that.
    render(panel({ shadow_mode: false }));

    const posture = screen.getByRole("status").textContent ?? "";
    expect(posture).toContain("Shadow mode is OFF");
    expect(posture).toContain("G-07");
  });
});

// --- criterion 2: a dead job appears with its reason ---------------------------------------------

describe("dead jobs", () => {
  it("shows the reason, not only the count", () => {
    render(panel());

    const list = screen.getByRole("list", { name: "Dead jobs" });
    expect(list.textContent).toContain("SYNTHETIC permanent failure");
    expect(list.textContent).toContain("research.capture_evidence");
  });

  it("flags one that needs a human", () => {
    render(panel());

    expect(screen.getByRole("list", { name: "Dead jobs" }).textContent).toContain("needs a human");
  });

  it("says how many there are when the sample is smaller than the total", () => {
    // The endpoint bounds the sample. A panel showing five of four hundred without saying so is
    // the §17.5 honesty problem in a different place.
    render(panel({ dead_jobs: 400 }));

    expect(document.body.textContent).toContain("400 in total");
  });

  it("states an empty state rather than rendering nothing", () => {
    render(panel({ dead_jobs: 0, dead_job_sample: [] }));

    expect(screen.queryByRole("list", { name: "Dead jobs" })).toBeNull();
    expect(document.body.textContent).toContain("No dead jobs");
  });
});

// --- criterion 3: a switch carries the typed reason, and surfaces refusals ------------------------

describe("the switches", () => {
  it("will not submit without a reason", () => {
    const stub = stubFetch(changed("global_pause", true));
    render(panel());

    submit("Turn on Global pause");

    expect(stub).not.toHaveBeenCalled();
  });

  it("will not submit a whitespace-only reason", () => {
    // The backend strips before checking; a button that let an administrator discover that by
    // being refused would waste a decision they had already made.
    const stub = stubFetch(changed("global_pause", true));
    render(panel());

    type("global_pause", "   ");
    submit("Turn on Global pause");

    expect(stub).not.toHaveBeenCalled();
  });

  it("sends the reason the administrator typed, and the direction implied by the current state", () => {
    const stub = stubFetch(changed("global_pause", true));
    render(panel());

    type("global_pause", "SYNTHETIC provider incident");
    submit("Turn on Global pause");

    return waitFor(() => {
      expect(stub).toHaveBeenCalled();
    }).then(() => {
      const body = stub.mock.calls[0]?.[1]?.body;
      if (typeof body !== "string") {
        throw new Error("the switch carried no JSON body");
      }
      expect(JSON.parse(body)).toEqual({
        enabled: true,
        reason: "SYNTHETIC provider incident",
      });
    });
  });

  it("turns a switch off when it is already on", () => {
    // The direction comes from the current state, so an operator cannot re-throw a switch that is
    // already thrown and believe they changed something.
    stubFetch(changed("global_pause", false));
    render(panel({ flags_in_force: ["global_pause"] }));

    expect(screen.getByRole("form", { name: "Turn off Global pause" })).toBeTruthy();
  });

  it("sends the token as a bearer", async () => {
    const stub = stubFetch(changed("shadow_mode", true));
    render(panel());

    type("shadow_mode", "SYNTHETIC");
    submit("Turn on Shadow mode");

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const headers = stub.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("shows the backend's own refusal", async () => {
    stubFetch(
      { detail: "your account does not have access to this. Ask an administrator for the pause_system permission." },
      403,
    );
    render(panel());

    type("global_pause", "SYNTHETIC");
    submit("Turn on Global pause");

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain(
        "does not have access",
      );
    });
  });

  it("refuses to send at all when there is no session", async () => {
    window.sessionStorage.clear();
    const stub = stubFetch(changed("global_pause", true));
    render(panel());

    type("global_pause", "SYNTHETIC");
    submit("Turn on Global pause");

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
  });

  it("reflects the new state after a successful change", async () => {
    stubFetch(changed("global_pause", true));
    render(panel());

    type("global_pause", "SYNTHETIC");
    submit("Turn on Global pause");

    await waitFor(() => {
      expect(screen.getByRole("form", { name: "Turn off Global pause" })).toBeTruthy();
    });
  });

  it("updates the posture from the response rather than assuming it", async () => {
    // Shadow mode is configuration *or* the flag, so releasing the flag may change nothing. The
    // response carries the effective answer; guessing it here would let the panel claim outreach
    // is live while the environment says otherwise.
    stubFetch(changed("shadow_mode", false, true));
    render(panel({ flags_in_force: ["shadow_mode"], shadow_mode: true }));

    type("shadow_mode", "SYNTHETIC");
    submit("Turn off Shadow mode");

    await waitFor(() => {
      expect(screen.getByRole("form", { name: "Turn on Shadow mode" })).toBeTruthy();
    });
    expect(screen.getByRole("status").textContent).toContain("Shadow mode is ON");
  });

  it("offers only the three system-wide switches", () => {
    // Scoped keys address one product or claim version and the endpoint refuses them; offering
    // one here would be a button that always fails.
    render(panel());

    const switches = within(screen.getByRole("list", { name: "Operational switches" })).getAllByRole(
      "listitem",
    );
    expect(switches).toHaveLength(3);
    expect(document.body.textContent).not.toContain("product_disabled");
  });

  it("says that turning a switch off starts nothing", () => {
    render(panel());

    expect(document.body.textContent).toContain("cannot enable anything");
  });
});

// --- §17.5 honesty: an unmeasured metric is stated, not shown as a zero ---------------------------

describe("the numbers", () => {
  it("shows the review backlog and the outbox depth", () => {
    render(panel());

    const text = document.body.textContent ?? "";
    expect(text).toContain("4 candidate(s)");
    expect(text).toContain("2 pending");
  });

  it("distinguishes an empty queue from one that just filled", () => {
    render(panel());

    expect(document.body.textContent).toContain("nothing waiting");
  });

  it("shows how many sends suppression refused", () => {
    // Measured since T-161. It was `null` with a stated reason, because `0` reads as "nothing is
    // being suppressed" — a claim nobody had checked — and a campaign whose every send was being
    // refused looked identical to one with nothing to send.
    render(panel());

    expect(document.body.textContent).toContain("3 send(s) refused");
  });

  it("shows a measured zero rather than hiding the row", () => {
    render(panel({ suppressed_send_attempts: 0 }));

    expect(document.body.textContent).toContain("0 send(s) refused");
  });

  it("states an unmeasured number rather than implying a zero", () => {
    // The list is empty today. The path stays proven, because it is the mechanism the *next*
    // unmeasured §17.5 number will use, and a rendering path nobody exercises is one that rots.
    render(panel({ not_measured: ["not measured: SYNTHETIC placeholder (T-999)"] }));

    expect(document.body.textContent).toContain("T-999");
  });

  it("renders no not-measured section when everything is measured", () => {
    render(panel());

    expect(screen.queryByRole("heading", { name: "Not measured" })).toBeNull();
  });
});
