// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewCard } from "../app/review/ReviewCard";
import type { CandidateDetail } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * The card tells the page when something changed (T-210; §12.3).
 *
 * `T-071d` found the card stating two contradictory things at once — "a draft has been queued"
 * above "no draft has been written for this candidate yet" — and a revision 1 still on screen
 * after revision 2 was saved. Both are one bug: the page fetched once, and every truth that
 * arrived afterwards had nowhere to land. So what is asserted here is the *wiring*: an action
 * that changed something tells the page, and the page is the only thing that refetches.
 */

const CANDIDATE_ID = "11111111-1111-4111-8111-111111111111";
const TOKEN = "SYNTHETIC-session-token";

const CANDIDATE = {
  candidate_id: CANDIDATE_ID,
  campaign_id: "22222222-2222-4222-8222-222222222222",
  campaign_name: "SYNTHETIC-Campaign",
  account_name: "SYNTHETIC-Account-Alpha",
  account_domain: "alpha.example.com",
  contact_name: "SYNTHETIC Person Alpha",
  contact_role: null,
  contact_points: [
    {
      contact_point_id: "66666666-6666-4666-8666-666666666666",
      type: "email",
      value: "synthetic.alpha@alpha.example.com",
      verification_state: "verified",
      approvable: true,
    },
  ],
  state: "review_pending",
  opportunity_type: "pilot",
  evidence: [],
  product_name: "SYNTHETIC-Product",
  product_readiness: "evaluation_or_pilot",
  product_readiness_summary: null,
  approved_claims: [],
  suppression: { contact_suppressed: false, account_suppressed: false },
  crm_relationship: null,
  current_revision: null,
  what_happens_next: "Nothing is sent.",
  record_version: "2026-08-14T08:00:00Z",
} as unknown as CandidateDetail;

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

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

describe("after an action that changed something", () => {
  it("tells the page, so the card can be refetched", async () => {
    stubFetch({
      candidate_id: CANDIDATE_ID,
      state: "approved",
      recipient: "synthetic.alpha@alpha.example.com",
      record_version: "2026-08-14T09:00:00Z",
    });
    const onChanged = vi.fn();
    render(<ReviewCard candidate={CANDIDATE} onChanged={onChanged} />);

    fireEvent.click(screen.getByLabelText("synthetic.alpha@alpha.example.com (email, verified)"));
    fireEvent.submit(screen.getByRole("form", { name: "Approve candidate" }));

    await waitFor(() => {
      expect(onChanged).toHaveBeenCalled();
    });
  });

  it("says nothing when the action was refused", async () => {
    // The control. A card that announced a change on every attempt would refetch after failures
    // too, and the reviewer would watch their refusal message disappear.
    stubFetch({ detail: "this candidate changed since it was loaded" }, 409);
    const onChanged = vi.fn();
    render(<ReviewCard candidate={CANDIDATE} onChanged={onChanged} />);

    fireEvent.click(screen.getByLabelText("synthetic.alpha@alpha.example.com (email, verified)"));
    fireEvent.submit(screen.getByRole("form", { name: "Approve candidate" }));

    await waitFor(() => {
      expect(screen.getByRole("alert")).toBeTruthy();
    });
    expect(onChanged).not.toHaveBeenCalled();
  });
});

describe("a candidate whose draft has been queued but not written", () => {
  const approved = { ...CANDIDATE, state: "approved" } as unknown as CandidateDetail;

  it("offers a way to look again", async () => {
    // `T-071d` run 3 found the draft "by guessing" — going back to the queue on a hunch. The
    // draft arrives from a worker moments later, so the card cannot know when; what it can do is
    // say so and offer the check.
    const onChanged = vi.fn();
    render(<ReviewCard candidate={approved} onChanged={onChanged} />);

    fireEvent.click(screen.getByRole("button", { name: "Check for the draft" }));

    await waitFor(() => {
      expect(onChanged).toHaveBeenCalled();
    });
  });

  it("offers no such button when there is nothing to wait for", () => {
    render(<ReviewCard candidate={CANDIDATE} onChanged={vi.fn()} />);

    expect(screen.queryByRole("button", { name: "Check for the draft" })).toBeNull();
  });
});
