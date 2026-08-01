// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApproveForm } from "../app/review/ApproveForm";
import type { CandidateDetail, ContactPointRow } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * Approving a candidate for an exact recipient (T-154b; §12.3 items 1 and 6, ADR-008).
 *
 * The three criteria are all about the reviewer *seeing what they approve*. ADR-008 approves an
 * exact recipient, and the failure it exists to prevent is an approval of an address nobody was
 * shown — so the tests are about what is on screen and what the button will not do, rather than
 * about the request shape alone.
 */

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "SYNTHETIC-session-token";

const VERIFIED: ContactPointRow = {
  contact_point_id: "22222222-2222-4222-8222-222222222222",
  type: "email",
  value: "synthetic.alpha@alpha.example.com",
  verification_state: "verified",
  approvable: true,
};

const UNVERIFIED: ContactPointRow = {
  contact_point_id: "33333333-3333-4333-8333-333333333333",
  type: "email",
  value: "synthetic.unverified@alpha.example.com",
  verification_state: "unverified",
  approvable: false,
};

const CANDIDATE: CandidateDetail = {
  candidate_id: CANDIDATE_ID,
  campaign_id: "44444444-4444-4444-8444-444444444444",
  campaign_name: "SYNTHETIC-Campaign",
  account_name: "SYNTHETIC-Account-Alpha",
  account_domain: "alpha.example.com",
  contact_name: "SYNTHETIC Person Alpha",
  contact_role: null,
  contact_points: [VERIFIED],
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

function approved(recipient = VERIFIED.value) {
  return {
    candidate_id: CANDIDATE_ID,
    recipient_contact_point_id: VERIFIED.contact_point_id,
    recipient,
    state: "approved",
    record_version: "2026-07-31T11:00:00Z",
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

function withPoints(...points: ContactPointRow[]): CandidateDetail {
  return { ...CANDIDATE, contact_points: points };
}

function choose(point: ContactPointRow) {
  fireEvent.click(screen.getByLabelText(new RegExp(point.value)));
}

function approve() {
  fireEvent.submit(screen.getByRole("form", { name: "Approve candidate" }));
}

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: the card lists the contact points with verification state ----------------------

describe("the recipient list", () => {
  it("shows each address with its verification state", () => {
    render(<ApproveForm candidate={withPoints(VERIFIED, UNVERIFIED)} />);

    // Asserted per row, and `verified` matched with a word boundary. A plain
    // `toContain("verified")` over the whole page is satisfied by the substring inside
    // "unverified" — so it would pass with the verified row's state missing entirely, which is
    // exactly the regression this is meant to catch.
    const verified = screen.getByLabelText(new RegExp(VERIFIED.value)).parentElement?.textContent;
    expect(verified).toMatch(/\bverified\b/);
    expect(verified).not.toMatch(/\bunverified\b/);

    const unverified = screen.getByLabelText(
      new RegExp(UNVERIFIED.value),
    ).parentElement?.textContent;
    expect(unverified).toMatch(/\bunverified\b/);
  });

  it("offers one option per address", () => {
    render(<ApproveForm candidate={withPoints(VERIFIED, UNVERIFIED)} />);

    expect(screen.getAllByRole("radio")).toHaveLength(2);
  });

  it("says so plainly when there is no address at all", () => {
    // Different from "the address is unusable", and it needs a different fix — one is a data
    // problem, the other is a research gap.
    render(<ApproveForm candidate={withPoints()} />);

    expect(screen.getByText(/No contact points are recorded/)).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Approve candidate" })).toBeNull();
  });

  it("states that approving sends nothing", () => {
    // A reviewer pressing a button labelled "Approve" deserves to know which of "queues a draft"
    // and "sends an email" they are causing.
    render(<ApproveForm candidate={CANDIDATE} />);

    const text = document.body.textContent ?? "";
    expect(text).toContain("Nothing is sent");
    expect(text).toContain("G-07");
  });
});

// --- criterion 2: approve cannot be submitted without a recipient chosen -------------------------

describe("choosing the recipient", () => {
  it("selects nothing by default", () => {
    // ADR-008 approves an address the reviewer chose. A pre-selected one is an address the system
    // chose and the approver ratified without deciding.
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    for (const radio of screen.getAllByRole<HTMLInputElement>("radio")) {
      expect(radio.checked).toBe(false);
    }
  });

  it("leaves Approve disabled until one is picked", () => {
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Approve" }).disabled).toBe(true);

    choose(VERIFIED);

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Approve" }).disabled).toBe(false);
  });

  it("sends nothing when submitted with no choice", () => {
    const stub = stubFetch(approved());
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    approve();

    expect(stub).not.toHaveBeenCalled();
  });

  it("sends the address the reviewer picked", async () => {
    const stub = stubFetch(approved());
    render(<ApproveForm candidate={withPoints(VERIFIED, { ...UNVERIFIED, approvable: true })} />);

    choose(UNVERIFIED);
    approve();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const body = stub.mock.calls[0]?.[1]?.body;
    if (typeof body !== "string") {
      throw new Error("the approval carried no JSON body");
    }
    expect(JSON.parse(body)).toMatchObject({
      recipient_contact_point_id: UNVERIFIED.contact_point_id,
    });
  });

  it("sends the record version the reviewer was shown", async () => {
    const stub = stubFetch(approved());
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    choose(VERIFIED);
    approve();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const body = stub.mock.calls[0]?.[1]?.body;
    if (typeof body !== "string") {
      throw new Error("the approval carried no JSON body");
    }
    expect(JSON.parse(body)).toMatchObject({ record_version: "2026-07-31T10:00:00Z" });
  });

  it("sends the token as a bearer", async () => {
    const stub = stubFetch(approved());
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    choose(VERIFIED);
    approve();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const headers = stub.mock.calls[0]?.[1]?.headers as Record<string, string>;
    expect(headers["authorization"]).toBe(`Bearer ${TOKEN}`);
  });
});

// --- criterion 3: an unverified address is shown as unusable, not absent -------------------------

describe("an unverified address", () => {
  it("is listed rather than hidden", () => {
    render(<ApproveForm candidate={withPoints(UNVERIFIED)} />);

    expect(screen.getByLabelText(new RegExp(UNVERIFIED.value))).toBeTruthy();
  });

  it("cannot be chosen", () => {
    render(<ApproveForm candidate={withPoints(VERIFIED, UNVERIFIED)} />);

    const unusable = screen.getByLabelText<HTMLInputElement>(new RegExp(UNVERIFIED.value));
    expect(unusable.disabled).toBe(true);
    const usable = screen.getByLabelText<HTMLInputElement>(new RegExp(VERIFIED.value));
    expect(usable.disabled).toBe(false);
  });

  it("says why it cannot be used", () => {
    render(<ApproveForm candidate={withPoints(UNVERIFIED)} />);

    expect(document.body.textContent).toContain("cannot be approved until it is verified");
  });

  it("warns when no address is usable", () => {
    render(<ApproveForm candidate={withPoints(UNVERIFIED)} />);

    expect(screen.getByRole("alert").textContent).toContain("cannot be approved yet");
  });

  it("does not warn when one is usable", () => {
    render(<ApproveForm candidate={withPoints(VERIFIED, UNVERIFIED)} />);

    expect(screen.queryByRole("alert")).toBeNull();
  });
});

// --- the outcome ----------------------------------------------------------------------------------

describe("after approving", () => {
  it("names the address that was approved", async () => {
    // An approval confirmed as "done" is one nobody can check. Named, a reviewer can catch
    // themselves having picked the wrong one.
    stubFetch(approved());
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    choose(VERIFIED);
    approve();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain(VERIFIED.value);
    });
    expect(screen.getByRole("status").textContent).toContain("nothing has been sent");
  });

  it("shows the backend's own refusal", async () => {
    stubFetch(
      {
        detail:
          "synthetic.unverified@alpha.example.com is unverified; an approval names an exact " +
          "recipient (ADR-008)",
      },
      409,
    );
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    choose(VERIFIED);
    approve();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("is unverified");
    });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("refuses to send at all when there is no session", async () => {
    window.sessionStorage.clear();
    const stub = stubFetch(approved());
    render(<ApproveForm candidate={withPoints(VERIFIED)} />);

    choose(VERIFIED);
    approve();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
    expect(screen.getByRole("alert").textContent).toContain("nothing was approved");
  });
});
