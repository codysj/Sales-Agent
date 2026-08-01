// @vitest-environment jsdom

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { ReviewQueue } from "../app/review/ReviewQueue";
import type { CandidateQueueRow, RevisionQueueRow } from "../lib/api";

/**
 * The review queue on screen (T-160; §12.3, §17.5).
 *
 * The gap this closes was not "the list looks wrong" — it was that a card could only be opened by
 * pasting a UUID. So the assertions are about **the link existing and pointing at the right
 * card**, about the backlog age a reviewer triages on being visible, and about an empty queue
 * saying it is empty. A test that only checked the account name was on screen would have passed
 * against a list nobody could click.
 */

const ALPHA: CandidateQueueRow = {
  candidate_id: "11111111-1111-4111-8111-111111111111",
  campaign_id: "44444444-4444-4444-8444-444444444444",
  campaign_name: "SYNTHETIC-Campaign",
  account_name: "SYNTHETIC-Account-Alpha",
  account_domain: "alpha.example.com",
  contact_name: "SYNTHETIC Person Alpha",
  state: "review_pending",
  record_version: "2026-07-31T10:00:00Z",
};

const BETA: CandidateQueueRow = {
  ...ALPHA,
  candidate_id: "22222222-2222-4222-8222-222222222222",
  account_name: "SYNTHETIC-Account-Beta",
  account_domain: "beta.example.com",
  contact_name: null,
};

const DRAFT: RevisionQueueRow = {
  revision_id: "33333333-3333-4333-8333-333333333333",
  candidate_id: ALPHA.candidate_id,
  campaign_id: ALPHA.campaign_id,
  campaign_name: "SYNTHETIC-Campaign",
  revision_number: 2,
  subject: "SYNTHETIC subject line",
  state: "review_pending",
  opportunity_type: "pilot_or_customer_testing",
  backlog_age_hours: 31,
  record_version: "2026-07-31T10:00:00Z",
};

function queue(
  candidates: CandidateQueueRow[],
  revisions: RevisionQueueRow[],
  totals?: { candidates?: number; revisions?: number },
) {
  return (
    <ReviewQueue
      candidates={candidates}
      candidateTotal={totals?.candidates ?? candidates.length}
      revisions={revisions}
      revisionTotal={totals?.revisions ?? revisions.length}
    />
  );
}

afterEach(() => {
  cleanup();
});

// --- criterion 1: candidates awaiting review, each linking to its card ---------------------------

describe("the candidate queue", () => {
  it("links each row to that candidate's card", () => {
    render(queue([ALPHA, BETA], []));
    const list = screen.getByRole("list", { name: "Candidate queue" });

    // Per row, and by href: a single `getAllByRole("link")` count would pass with both rows
    // pointing at the same card, which is the failure that makes a queue useless.
    const links = within(list).getAllByRole<HTMLAnchorElement>("link");
    expect(links.map((anchor) => anchor.getAttribute("href"))).toEqual([
      `/review/${ALPHA.candidate_id}`,
      `/review/${BETA.candidate_id}`,
    ]);
  });

  it("names the account, contact, and campaign on each row", () => {
    render(queue([ALPHA], []));

    const row = within(screen.getByRole("list", { name: "Candidate queue" })).getByRole("listitem");
    const text = row.textContent ?? "";
    expect(text).toContain(ALPHA.account_name);
    expect(text).toContain(ALPHA.account_domain);
    expect(text).toContain("SYNTHETIC Person Alpha");
    expect(text).toContain("SYNTHETIC-Campaign");
  });

  it("says so when a candidate has no contact rather than leaving a gap", () => {
    // `contact_name` is nullable and an empty space reads as a rendering fault. A reviewer needs
    // to know the candidate has nobody on it, because that is a different problem to fix.
    render(queue([BETA], []));

    expect(screen.getByRole("list", { name: "Candidate queue" }).textContent).toContain(
      "no contact on this candidate",
    );
  });
});

// --- criterion 2: revisions awaiting approval, with backlog age ----------------------------------

describe("the revision queue", () => {
  it("shows how long each revision has been waiting", () => {
    render(queue([], [DRAFT]));

    const row = within(screen.getByRole("list", { name: "Revision queue" })).getByRole("listitem");
    expect(row.textContent).toContain("waiting 31 hours");
  });

  it("links a revision to the card where it is reviewed", () => {
    // The *candidate's* card: there is no per-revision page, and the card is where the draft,
    // its evidence, and the approve action live.
    render(queue([], [DRAFT]));

    const link = within(screen.getByRole("list", { name: "Revision queue" })).getByRole<
      HTMLAnchorElement
    >("link");
    expect(link.getAttribute("href")).toBe(`/review/${DRAFT.candidate_id}`);
    expect(link.textContent).toBe(DRAFT.subject);
  });

  it("reports an unqualified opportunity type as unknown rather than omitting it", () => {
    render(queue([], [{ ...DRAFT, opportunity_type: null }]));

    expect(screen.getByRole("list", { name: "Revision queue" }).textContent).toContain(
      "opportunity type not yet qualified",
    );
  });

  it("keeps the two queues separate", () => {
    // They are separate lifecycles (ADR-015) and a reviewer works them differently; merging them
    // would invent an ordering neither endpoint has.
    render(queue([ALPHA], [DRAFT]));

    expect(screen.getByRole("list", { name: "Candidate queue" })).toBeTruthy();
    expect(screen.getByRole("list", { name: "Revision queue" })).toBeTruthy();
  });
});

// --- criterion 3: an empty queue says it is empty -------------------------------------------------

describe("an empty queue", () => {
  it("states that nothing is waiting, for each queue independently", () => {
    render(queue([], []));

    const text = document.body.textContent ?? "";
    expect(text).toContain("No candidates are waiting for review.");
    expect(text).toContain("No message revisions are waiting for approval.");
  });

  it("renders no list at all when there is nothing in it", () => {
    render(queue([], []));

    expect(screen.queryByRole("list", { name: "Candidate queue" })).toBeNull();
    expect(screen.queryByRole("list", { name: "Revision queue" })).toBeNull();
  });

  it("says the other queue is empty even when one has rows", () => {
    // The failure this catches: an empty state rendered once for the page rather than per queue,
    // so a reviewer with candidates waiting cannot tell whether there are no revisions or the
    // revision queue silently failed to load.
    render(queue([ALPHA], []));

    expect(document.body.textContent ?? "").toContain(
      "No message revisions are waiting for approval.",
    );
  });
});

// --- the page is one page of possibly many -------------------------------------------------------

describe("when there is more than one page", () => {
  it("says how many are not shown", () => {
    // `total` comes from the endpoint. Without this a reviewer works ten rows believing that is
    // the whole backlog, which is exactly the number §17.5 wants an operational view to be honest
    // about.
    render(queue([ALPHA], [DRAFT], { candidates: 40, revisions: 12 }));

    const text = document.body.textContent ?? "";
    expect(text).toContain("Showing 1 of 40");
    expect(text).toContain("Showing 1 of 12");
  });

  it("stays quiet when the page is the whole queue", () => {
    render(queue([ALPHA], [DRAFT]));

    expect(document.body.textContent ?? "").not.toContain("Showing");
  });
});
