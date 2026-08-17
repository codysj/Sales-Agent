// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { AttentionList } from "../app/attention/AttentionList";
import { StrandedRevisionList } from "../app/attention/StrandedRevisionList";
import type { StrandedRevisionRow } from "../lib/api";

/**
 * Drafts nobody can approve, on screen (T-209; §7.5).
 *
 * `T-071d` reached this dead end in two runs of three, and what made it P0 was not that the draft
 * was broken — it was that nothing said so. The assertions are therefore about what a reviewer
 * *sees*: that the item is there at all, that it says why in words that need no specification
 * open, that it says what to do next, and that the page does not simultaneously reassure them
 * that nothing needs attention.
 */

const REVISION_ID = "77777777-7777-4777-8777-777777777777";
const CANDIDATE_ID = "88888888-8888-4888-8888-888888888888";

function row(overrides: Partial<StrandedRevisionRow> = {}): StrandedRevisionRow {
  return {
    revision_id: REVISION_ID,
    candidate_id: CANDIDATE_ID,
    campaign_id: "99999999-9999-4999-8999-999999999999",
    campaign_name: "SYNTHETIC-Campaign",
    account_name: "SYNTHETIC-Account",
    revision_number: 2,
    subject: "SYNTHETIC edited subject",
    failures: [
      {
        check: "product_statement_grounding",
        reason: "the body is not the rendered template plus the cited claims",
        inputs: { revision_id: REVISION_ID },
      },
    ],
    refusal_reason: null,
    refusal_notes: null,
    record_version: "2026-08-14T10:00:00Z",
    ...overrides,
  };
}

/** A draft a person refused, rather than one a check refused (`T-208`). */
function refused(overrides: Partial<StrandedRevisionRow> = {}): StrandedRevisionRow {
  return row({
    failures: [],
    refusal_reason: "tone_or_positioning_problem",
    refusal_notes: null,
    ...overrides,
  });
}

afterEach(() => {
  cleanup();
});

// --- criterion 1: the stranded draft is visible ---------------------------------------------------

describe("a stranded draft", () => {
  it("is listed with the account and campaign it belongs to", () => {
    render(<StrandedRevisionList rows={[row()]} />);

    const item = screen.getByRole("list", { name: "Stranded drafts" }).textContent ?? "";
    expect(item).toContain("SYNTHETIC-Account");
    expect(item).toContain("SYNTHETIC-Campaign");
    expect(item).toContain("SYNTHETIC edited subject");
  });

  it("explains the failing check in words, and keeps the system's name beside it", () => {
    // `product_statement_grounding` is what the rule is called, not what it means. A reviewer
    // holding no specification can act on the sentence; whoever debugs this can still search for
    // the name.
    render(<StrandedRevisionList rows={[row()]} />);

    const item = screen.getByRole("list", { name: "Stranded drafts" }).textContent ?? "";
    expect(item).toContain("not one of the approved claims it cites");
    expect(item).toContain("product_statement_grounding");
    expect(item).toContain("the body is not the rendered template plus the cited claims");
  });

  it("says what to do next, and links to the candidate", () => {
    // The dead end was not "the draft failed" — a failed revision is still editable. It was that
    // no screen said so, and one run spent five revisions finding out.
    render(<StrandedRevisionList rows={[row()]} />);

    const link = screen.getByRole<HTMLAnchorElement>("link", { name: "Open this candidate" });
    expect(link.getAttribute("href")).toBe(`/review/${CANDIDATE_ID}`);
    expect(screen.getByRole("list", { name: "Stranded drafts" }).textContent).toContain("can still be edited");
  });

  it("glosses every check the backend can send", () => {
    // There is no runtime fallback and deliberately so: `CHECKS` is keyed by the generated union,
    // so a check added to the backend fails `npm run typecheck` rather than rendering as a blank
    // explanation. This asserts the other half of that — that each gloss is a real sentence, not
    // the check name echoed back.
    const checks: Array<StrandedRevisionRow["failures"][number]["check"]> = [
      "claim_citations",
      "claim_currency",
      "campaign_scope",
      "product_readiness",
      "evidence_citations",
      "recipient_contactable",
      "suppression",
      "product_statement_grounding",
      "compliance_elements",
      "evidence_for_personalization",
    ];

    render(
      <StrandedRevisionList
        rows={checks.map((check, index) =>
          row({
            revision_id: `${index}`,
            failures: [{ check, reason: "SYNTHETIC reason", inputs: {} }],
          }),
        )}
      />,
    );

    const text = screen.getByRole("list", { name: "Stranded drafts" }).textContent ?? "";
    for (const check of checks) {
      // Every gloss says something the check name does not, and none of them is empty.
      expect(text).toContain(`Recorded as ${check}`);
    }
    expect(text).not.toContain("undefined");
  });
});

// --- T-208: a draft a person refused is a different situation from one a check refused -----------

describe("a refused draft", () => {
  it("says a person decided, and does not show validation checks", () => {
    // A row that showed both identically would ask a reviewer to redo a judgement that has
    // already been made.
    render(<StrandedRevisionList rows={[refused()]} />);

    const text = screen.getByRole("list", { name: "Stranded drafts" }).textContent ?? "";
    expect(text).toContain("A reviewer decided these words should not be sent");
    expect(text).toContain("the tone or positioning was wrong");
    expect(text).not.toContain("Recorded as");
  });

  it("shows the reviewer's own words when they left any", () => {
    render(
      <StrandedRevisionList
        rows={[refused({ refusal_notes: "SYNTHETIC: it reads like a mailshot" })]}
      />,
    );

    expect(screen.getByRole("list", { name: "Stranded drafts" }).textContent).toContain(
      "SYNTHETIC: it reads like a mailshot",
    );
  });

  it("says nothing will write a replacement by itself", () => {
    // The honest next step, and the reason a refusal belongs on this page at all: after it, the
    // candidate has no message anyone can approve and nothing is going to produce one.
    render(<StrandedRevisionList rows={[refused()]} />);

    const text = screen.getByRole("list", { name: "Stranded drafts" }).textContent ?? "";
    expect(text).toContain("Nothing writes a replacement by itself");
    expect(screen.getByRole<HTMLAnchorElement>("link", { name: "Open this candidate" })).toBeTruthy();
  });

  it("points at the one thing that actually works", () => {
    // `T-211`. Both rows used to offer "or reject the candidate", which is impossible for
    // anything on this page: a candidate only gets a draft by being approved, and §8.2 gives an
    // approved candidate one edge, to `invalidated`. Advice a reviewer cannot follow costs them
    // the attempt before they find out.
    render(<StrandedRevisionList rows={[refused(), row({ revision_id: "other" })]} />);

    const text = screen.getByRole("list", { name: "Stranded drafts" }).textContent ?? "";
    expect(text).not.toContain("reject the candidate");
    expect(screen.getAllByRole("link", { name: "Open this candidate" })).toHaveLength(2);
  });

  it("does not tell a reviewer the draft can still be edited", () => {
    // True of a validation failure and false here: a refused revision is not editable, and
    // repeating that sentence would send a reviewer to a control that will refuse them.
    render(<StrandedRevisionList rows={[refused()]} />);

    expect(screen.getByRole("list", { name: "Stranded drafts" }).textContent).not.toContain(
      "can still be edited",
    );
  });
});

// --- criterion 3: the page does not say everything is fine ---------------------------------------

describe("the attention page as a whole", () => {
  it("does not reassure a reviewer while a draft is stuck", () => {
    // The negative control is the pair. Rendered together with no stale approvals — the exact
    // state `T-071d` hit — the approvals half must not speak for the page.
    render(
      <>
        <AttentionList rows={[]} />
        <StrandedRevisionList rows={[row()]} />
      </>,
    );

    expect(screen.queryByText(/Nothing needs attention/)).toBeNull();
    expect(screen.getByRole("list", { name: "Stranded drafts" })).toBeTruthy();
  });

  it("says both halves are healthy when both are empty", () => {
    render(
      <>
        <AttentionList rows={[]} />
        <StrandedRevisionList rows={[]} />
      </>,
    );

    expect(screen.getByText(/No approval needs attention/)).toBeTruthy();
    expect(screen.getByText(/No draft is stuck/)).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Stranded drafts" })).toBeNull();
  });
});
