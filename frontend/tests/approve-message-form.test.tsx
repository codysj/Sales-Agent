// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApproveMessageForm } from "../app/review/ApproveMessageForm";
import type { CandidateDetail, ContactPointRow } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * Approving the exact words (T-205; §12.3 item 6, §11.3, ADR-008).
 *
 * This control did not exist until `T-205`, and its absence is why it is tested this closely. The
 * endpoint, the permission, the queue entry advertising "Messages awaiting approval", and the
 * generated type were all present and correct; nothing called any of it. Three independent
 * rehearsal readers reached the drafted message, formed a view on it, and had nowhere to put that
 * view (`T-071c`). So the tests here are about what a reviewer can *do* and what the button will
 * refuse to do — not about the request shape alone.
 */

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "55555555-5555-4555-8555-555555555555";
const TOKEN = "SYNTHETIC-session-token";
const REVISION_VERSION = "2026-08-11T09:00:00Z";

const VERIFIED: ContactPointRow = {
  contact_point_id: "22222222-2222-4222-8222-222222222222",
  type: "email",
  value: "synthetic.alpha@alpha.example.com",
  verification_state: "verified",
  approvable: true,
};

function candidateWith(revisionState: string): CandidateDetail {
  return {
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
    current_revision: {
      revision_id: REVISION_ID,
      revision_number: 1,
      state: revisionState,
      subject: "SYNTHETIC subject",
      body: "SYNTHETIC body",
      content_hash: "SYNTHETIC-hash",
      evidence_ids: [],
      approved_claim_ids: [],
      record_version: REVISION_VERSION,
    },
    what_happens_next: "Nothing is sent.",
    record_version: "2026-08-11T08:00:00Z",
  } as unknown as CandidateDetail;
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

const APPROVED = {
  approval_id: "66666666-6666-4666-8666-666666666666",
  message_revision_id: REVISION_ID,
  send_command_id: "77777777-7777-4777-8777-777777777777",
  recipient: VERIFIED.value,
  revision_state: "approved",
  what_happens_next:
    "Nothing is sent. The approval and an immutable send command are recorded, and the worker dispatches only to the fake adapter while shadow mode is on.",
  record_version: REVISION_VERSION,
};

beforeEach(() => {
  sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("approving the exact words", () => {
  it("offers the control at all, which is the whole of T-205", () => {
    render(<ApproveMessageForm candidate={candidateWith("review_pending")} />);

    expect(screen.getByRole("form", { name: "Approve message" })).toBeTruthy();
  });

  it("will not approve until a recipient is chosen", () => {
    // ADR-008 approves an exact address. A pre-selected one is an address the form chose and the
    // reviewer ratified without deciding, which is the failure the disabled state prevents.
    render(<ApproveMessageForm candidate={candidateWith("review_pending")} />);
    const button = screen.getByRole("button", { name: "Approve these words" });

    expect((button as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByLabelText(new RegExp(VERIFIED.value)));

    expect((button as HTMLButtonElement).disabled).toBe(false);
  });

  it("approves the revision, for the chosen address, pinned to the text that was read", async () => {
    const stub = stubFetch(APPROVED);
    render(<ApproveMessageForm candidate={candidateWith("review_pending")} />);

    fireEvent.click(screen.getByLabelText(new RegExp(VERIFIED.value)));
    fireEvent.submit(screen.getByRole("form", { name: "Approve message" }));

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const [url, init] = stub.mock.calls[0] as [string, RequestInit];

    expect(url).toBe(`/api/review/revisions/${REVISION_ID}/approve`);
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      recipient_contact_point_id: VERIFIED.contact_point_id,
      // Sent, not omitted. The backend refuses a revision that changed since it was loaded, and
      // that refusal is the only thing guaranteeing the approver approved the text they read.
      record_version: REVISION_VERSION,
    });
  });

  it("reports what happened in the backend's own words", async () => {
    // Not a local paraphrase: the API is the only party that knows whether shadow mode is on, and
    // a sentence duplicated here would drift the day that changes.
    stubFetch(APPROVED);
    render(<ApproveMessageForm candidate={candidateWith("review_pending")} />);

    fireEvent.click(screen.getByLabelText(new RegExp(VERIFIED.value)));
    fireEvent.submit(screen.getByRole("form", { name: "Approve message" }));

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain(APPROVED.what_happens_next);
    });
    expect(screen.getByRole("status").textContent).toContain(VERIFIED.value);
  });

  it.each(["superseded", "invalidated"])(
    "offers no approval for a %s revision, and says why",
    (state) => {
      // The backend answers 409 for these. A form that submitted into a guaranteed refusal would
      // teach a reviewer that refusals are routine, which is the opposite of what they mean here.
      render(<ApproveMessageForm candidate={candidateWith(state)} />);

      expect(screen.queryByRole("form", { name: "Approve message" })).toBeNull();
      expect(screen.getByText(new RegExp(state === "superseded" ? "superseded" : "invalidated"))).toBeTruthy();
    },
  );

  it("renders nothing when there is no draft yet", () => {
    const candidate = candidateWith("review_pending");
    const { container } = render(
      <ApproveMessageForm candidate={{ ...candidate, current_revision: null }} />,
    );

    expect(container.textContent).toBe("");
  });

  it("shows the backend's refusal rather than a generic failure", async () => {
    // `T-071c` found the cost of the opposite: a reader stuck at this exact point was shown
    // "§8.3 step 8 presents a candidate for review before step 9 drafts for it". Whatever the
    // backend says here is at least addressed to the person reading it.
    stubFetch(
      { detail: "this revision changed since it was loaded; reload the card before approving" },
      409,
    );
    render(<ApproveMessageForm candidate={candidateWith("review_pending")} />);

    fireEvent.click(screen.getByLabelText(new RegExp(VERIFIED.value)));
    fireEvent.submit(screen.getByRole("form", { name: "Approve message" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("reload the card before approving");
    });
  });

  it("refuses to submit when nobody is signed in", async () => {
    sessionStorage.clear();
    const stub = stubFetch(APPROVED);
    render(<ApproveMessageForm candidate={candidateWith("review_pending")} />);

    fireEvent.click(screen.getByLabelText(new RegExp(VERIFIED.value)));
    fireEvent.submit(screen.getByRole("form", { name: "Approve message" }));

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
  });
});
