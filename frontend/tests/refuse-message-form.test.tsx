// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { RefuseMessageForm } from "../app/review/RefuseMessageForm";
import type { CandidateDetail, ContactPointRow } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * Refusing the words, without writing replacements (T-208; §12.3 items 6-7, §10.6).
 *
 * `T-071d`: three readers of three decided the draft must not go out, and **not one could record
 * it**. So what is tested here is a reviewer's ability to say *no* and have it stick — that the
 * control appears where the decision is taken, that it needs no replacement text, that it will
 * not submit without a §10.6 reason, and that it stays a decision about the message rather than
 * about the company.
 */

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const REVISION_ID = "55555555-5555-4555-8555-555555555555";
const TOKEN = "SYNTHETIC-session-token";
const REVISION_VERSION = "2026-08-14T09:00:00Z";

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
    record_version: "2026-08-14T08:00:00Z",
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

const RECORDED = {
  message_revision_id: REVISION_ID,
  revision_state: "invalidated",
  reason: "tone_or_positioning_problem",
  what_happens_next: "The candidate itself is unchanged. Nothing writes a replacement.",
  record_version: "2026-08-14T09:05:00Z",
};

function choose(reason: string) {
  fireEvent.change(screen.getByLabelText("What is wrong with these words?"), {
    target: { value: reason },
  });
}

function submit() {
  fireEvent.submit(screen.getByRole("form", { name: "Refuse message" }));
}

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: a refusal is recordable, and needs no replacement text --------------------------

describe("refusing a draft's wording", () => {
  it("offers the decision on a revision awaiting approval", () => {
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    expect(screen.getByRole("form", { name: "Refuse message" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Do not send these words" })).toBeTruthy();
  });

  it("asks for no replacement text of any kind", () => {
    // The whole finding. A reviewer with no better wording must still be able to say no.
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    expect(screen.queryByLabelText("Subject")).toBeNull();
    expect(screen.queryByLabelText("Body")).toBeNull();
  });

  it("sends the reason, the record version, and the bearer token", async () => {
    const stub = stubFetch(RECORDED);
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    choose("tone_or_positioning_problem");
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const [url, init] = stub.mock.calls[0] ?? [];
    expect(String(url)).toBe(`/api/review/revisions/${REVISION_ID}/refuse`);
    expect(JSON.parse(init?.body as string)).toEqual({
      reason: "tone_or_positioning_problem",
      record_version: REVISION_VERSION,
    });
    expect((init?.headers as Record<string, string>)["authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("carries the reviewer's notes when they wrote any", async () => {
    const stub = stubFetch(RECORDED);
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    choose("unsupported_claim");
    fireEvent.change(screen.getByLabelText("Anything to add? (optional)"), {
      target: { value: "SYNTHETIC: the second paragraph overstates it" },
    });
    submit();

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    expect(JSON.parse(stub.mock.calls[0]?.[1]?.body as string)).toMatchObject({
      notes: "SYNTHETIC: the second paragraph overstates it",
    });
  });

  it("will not submit without a reason", () => {
    const stub = stubFetch(RECORDED);
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    const button = screen.getByRole<HTMLButtonElement>("button", {
      name: "Do not send these words",
    });
    expect(button.disabled).toBe(true);

    submit();

    expect(stub).not.toHaveBeenCalled();
  });

  it("offers only the three reasons that are about the message", () => {
    // §10.6's other eight are about the candidate. Offering them would let a reviewer file a true
    // statement against the wrong object, and the backend's schema refuses them anyway.
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    const options = screen
      .getAllByRole<HTMLOptionElement>("option")
      .map((option) => option.value)
      .filter((value) => value !== "");
    expect(options).toEqual([
      "tone_or_positioning_problem",
      "unsupported_claim",
      "personalization_not_useful",
    ]);
  });

  it("reports what happened in the backend's own words", async () => {
    stubFetch(RECORDED);
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    choose("tone_or_positioning_problem");
    submit();

    await waitFor(() => {
      expect(screen.getByRole("status").textContent).toContain("can no longer be approved");
    });
    expect(screen.getByRole("status").textContent).toContain("Nothing writes a replacement");
  });

  it("shows the backend's refusal and keeps the form", async () => {
    stubFetch({ detail: "this revision changed since it was loaded; reload the card" }, 409);
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    choose("tone_or_positioning_problem");
    submit();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("reload the card");
    });
    expect(screen.getByRole("form", { name: "Refuse message" })).toBeTruthy();
  });

  it("refuses to send at all when there is no session", async () => {
    window.sessionStorage.clear();
    const stub = stubFetch(RECORDED);
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    choose("tone_or_positioning_problem");
    submit();

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
  });
});

// --- criterion 2: it is a decision about the message, not about the candidate ---------------------

describe("what the control says it is", () => {
  it("says the candidate is untouched, before the decision is taken", () => {
    render(<RefuseMessageForm candidate={candidateWith("review_pending")} />);

    const text = screen.getByRole("region", { name: "These words should not be sent" }).textContent;
    expect(text).toContain("the candidate stays exactly as it is");
    expect(text).toContain("not a rejection of the company");
  });
});

// --- the states it appears in --------------------------------------------------------------------

describe("where the control appears", () => {
  it("also appears on a draft that failed validation", () => {
    // Broken and wrong is a real combination, and the server's `REFUSABLE_STATES` allows it.
    render(<RefuseMessageForm candidate={candidateWith("validation_failed")} />);

    expect(screen.getByRole("form", { name: "Refuse message" })).toBeTruthy();
  });

  it.each(["approved", "superseded", "invalidated"])(
    "renders nothing for a %s revision",
    (state) => {
      // A decision already stands on each of these. A form that submitted into a guaranteed 409
      // would teach a reviewer that refusals are normal.
      const { container } = render(<RefuseMessageForm candidate={candidateWith(state)} />);

      expect(container.innerHTML).toBe("");
    },
  );

  it("renders nothing when there is no draft to refuse", () => {
    const candidate = candidateWith("review_pending");
    const { container } = render(
      <RefuseMessageForm candidate={{ ...candidate, current_revision: null }} />,
    );

    expect(container.innerHTML).toBe("");
  });
});
