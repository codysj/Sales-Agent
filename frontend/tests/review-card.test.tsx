import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { ReviewCard } from "../app/review/ReviewCard";
import type { CandidateDetail } from "../lib/api";

/**
 * The review card shows what §12.3 requires (T-064).
 *
 * Rendered with `react-dom/server` rather than a DOM testing library. The card is static — no
 * state, no effects, no interactivity yet — so `renderToStaticMarkup` exercises everything there
 * is to exercise, and adding `jsdom` plus a testing library for it would be three dependencies
 * bought against a need nobody has. ADR-021 says nothing is added before a screen needs it;
 * `T-065` gives the actions behaviour, and that is when a DOM renderer earns its place.
 *
 * The assertions are deliberately about **the reviewer's information**, not about markup: that
 * the source quality and retrieval time appear, that a suppression warning appears when one
 * applies, that the card says nothing will be sent. A test asserting class names would pass
 * while the card told a reviewer nothing.
 */

const FULL: CandidateDetail = {
  candidate_id: "11111111-1111-4111-8111-111111111111",
  campaign_id: "22222222-2222-4222-8222-222222222222",
  campaign_name: "SYNTHETIC-Sodium Battery Campaign",
  account_name: "SYNTHETIC-Account-Alpha",
  account_domain: "alpha.example.com",
  contact_name: "SYNTHETIC Person Alpha",
  contact_role: "Head of SYNTHETIC Operations",
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
  evidence: [
    {
      evidence_id: "33333333-3333-4333-8333-333333333333",
      excerpt: "SYNTHETIC: the account is described as evaluating stationary storage.",
      source_type: "synthetic_fixture",
      source_quality: "high",
      retrieved_at: "2026-07-30T09:15:00Z",
      expires_or_refresh_by: null,
      contains_personal_or_confidential_data: false,
    },
  ],
  product_name: "SYNTHETIC-Sodium Storage Module",
  product_readiness: "evaluation_or_pilot",
  product_readiness_summary: "SYNTHETIC placeholder readiness.",
  approved_claims: [
    {
      claim_id: "44444444-4444-4444-8444-444444444444",
      claim_key: "SYNTHETIC-CLAIM-sodium-readiness",
      version: 1,
      text: "SYNTHETIC EXAMPLE CLAIM — offered for evaluation deployments.",
      expires_or_review_by: null,
    },
  ],
  suppression: { contact_suppressed: false, account_suppressed: false },
  crm_relationship: null,
  current_revision: {
    revision_id: "55555555-5555-4555-8555-555555555555",
    revision_number: 1,
    subject: "SYNTHETIC subject line",
    body: "SYNTHETIC body paragraph.",
    state: "review_pending",
    approved_claim_ids: ["44444444-4444-4444-8444-444444444444"],
    evidence_ids: ["33333333-3333-4333-8333-333333333333"],
    content_hash: "a".repeat(64),
    record_version: "2026-07-31T10:00:00Z",
  },
  what_happens_next:
    "Nothing is sent. This build runs in shadow mode: approving records the decision and creates " +
    "no outbound message. Live sending is gated (G-07) and needs a separate, explicit authorization.",
  record_version: "2026-07-31T10:00:00Z",
};

function render(candidate: CandidateDetail = FULL): string {
  return renderToStaticMarkup(<ReviewCard candidate={candidate} />);
}

/** §12.3's seven, and a string that must appear for each. */
const REQUIRED_ELEMENTS: ReadonlyArray<readonly [string, readonly string[]]> = [
  [
    "1. Account, contact, campaign, and proposed opportunity type",
    ["SYNTHETIC-Account-Alpha", "SYNTHETIC Person Alpha", "SYNTHETIC-Sodium Battery Campaign", "pilot"],
  ],
  ["2. Strongest evidence, source quality, and retrieval time", ["evaluating stationary storage", "high", "2026-07-30 09:15 UTC"]],
  ["3. Product readiness and approved claims", ["evaluation_or_pilot", "SYNTHETIC-CLAIM-sodium-readiness"]],
  ["4. CRM relationship and suppression warnings", ["No suppression recorded", "CRM relationship: not checked"]],
  ["5. Exact revision and what happens next", ["SYNTHETIC subject line", "SYNTHETIC body paragraph.", "Nothing is sent"]],
  ["6. Actions", ["Approve", "Edit this draft", "Reject", "Defer", "Request more research"]],
  ["7. Structured correction reason", ["Why is this being corrected?", "Evidence does not support the claim"]],
];

describe("the review card shows §12.3's seven elements", () => {
  it.each(REQUIRED_ELEMENTS)("shows %s", (_item, expected) => {
    const html = render();

    for (const fragment of expected) {
      expect(html).toContain(fragment);
    }
  });

  it("checks every one of the seven", () => {
    // A guard on the guard: dropping a row from the table above would quietly stop checking an
    // element, and the suite would still be green.
    expect(REQUIRED_ELEMENTS).toHaveLength(7);
  });
});

describe("evidence", () => {
  it("shows retrieval time as a date a reviewer can judge staleness by", () => {
    const html = render();

    // Not "yesterday": a relative phrase rounds last week and last month toward each other, and
    // whether evidence is stale is exactly the judgement §12.3 item 2 asks the reviewer to make.
    expect(html).toContain("2026-07-30 09:15 UTC");
    // And machine-readable alongside the human one. Matched case-insensitively: React 19 emits
    // `dateTime` verbatim where older versions lowercased it, HTML attribute names are
    // case-insensitive either way, and a test that pinned the casing would break on an upgrade
    // without anything actually being wrong.
    expect(/<time [^>]*datetime="2026-07-30T09:15:00Z"/i.test(html)).toBe(true);
  });

  it("says so plainly when there is none", () => {
    const html = render({ ...FULL, evidence: [] });

    expect(html).toContain("None recorded");
  });

  it("flags evidence containing personal data", () => {
    const html = render({
      ...FULL,
      evidence: [{ ...FULL.evidence[0]!, contains_personal_or_confidential_data: true }],
    });

    expect(html).toContain("Contains personal or confidential data");
  });
});

describe("what the card refuses to invent", () => {
  it("says readiness is not stated rather than guessing", () => {
    // GP-12: technical relevance is not availability. A card that implied availability would be
    // the worst possible default.
    const html = render({ ...FULL, product_readiness: null, product_readiness_summary: null });

    expect(html).toContain("Not stated");
  });

  it("reports the CRM as not checked, never as no relationship", () => {
    const html = render();

    expect(html).toContain("not checked");
    expect(html).not.toContain("No CRM relationship");
    expect(html).toContain("Q-001");
  });

  it("says when no draft exists rather than showing an empty message", () => {
    const html = render({ ...FULL, current_revision: null });

    expect(html).toContain("No draft has been written");
  });
});

describe("suppression", () => {
  it("warns loudly when the contact is suppressed", () => {
    const html = render({
      ...FULL,
      suppression: { contact_suppressed: true, account_suppressed: false },
    });

    expect(html).toContain("Do not approve outreach");
    expect(html).toContain('role="alert"');
    expect(html).toContain("this contact");
  });

  it("names both scopes when both apply", () => {
    const html = render({
      ...FULL,
      suppression: { contact_suppressed: true, account_suppressed: true },
    });

    expect(html).toContain("this contact and this account");
  });
});

describe("shadow mode", () => {
  it("states that no send will occur", () => {
    // The acceptance criterion names this explicitly, and it is the one sentence whose absence
    // would let a reviewer believe they had just sent an email.
    const html = render();

    expect(html).toContain("Nothing is sent");
    expect(html).toContain("shadow mode");
    expect(html).toContain("G-07");
  });

  it("offers all five of §12.3 item 6's actions, every one of them live", () => {
    // The end of a sequence: `T-065b` wired Edit, `T-154b` Approve, `T-066b2` Reject and Defer,
    // and `T-155` Request-more-research. Nothing is offered as a placeholder any more.
    //
    // Asserted by *label*, not by counting: the counts happened to stay 5-and-4 when Approve went
    // live, because its submit starts disabled until a recipient is chosen. A test that only
    // counted would have kept passing while saying nothing.
    const html = render();
    const buttons = html.match(/<button[^>]*>[^<]*/g) ?? [];
    const labels = new Set(buttons.map((button) => button.split(">")[1]));

    expect(labels).toEqual(
      new Set([
        "Save as a new revision",
        "Approve",
        "Reject",
        "Defer",
        "Request more research",
      ]),
    );
  });

  it("shows no disabled placeholder buttons at all", () => {
    // `T-155`'s criterion 3, and the property that would regress silently: every disabled button
    // here belongs to a *live* form and is waiting on a choice the reviewer has not made yet — a
    // recipient, a category, a waypoint. None of them is an action that does not exist.
    const html = render();
    const buttons = html.match(/<button[^>]*>[^<]*/g) ?? [];
    const disabled = buttons.filter((button) => button.includes("disabled"));

    expect(html).not.toContain("Not yet wired");
    for (const button of disabled) {
      expect(button).toMatch(/title="(Choose|A deferral needs)/);
    }
    // Edit's submit is live from the start: it has nothing to choose first.
    expect(html).toContain("Save as a new revision");
    expect(html).toContain("Choose the address this message would go to");
    expect(html).toContain("A deferral needs a date or an event");
  });

  it("offers the structured correction reason on the form that uses it", () => {
    // §12.3 item 7. It moved out of the card and into `T-065b`'s form, where it is `required`
    // rather than disabled — the same requirement, now at the point of entry.
    const html = render();
    const select = /<select[^>]*>/.exec(html)?.[0] ?? "";

    expect(select).toContain("required");
    expect(select).not.toContain("disabled");
  });
});

describe("the card fetches nothing", () => {
  it("renders from a prop", () => {
    // Structural: a component that fetched its own data could not be rendered in a test without
    // a server, and `lib/api.ts` is the only module permitted to reach the backend.
    const html = render();

    expect(html).toContain("SYNTHETIC-Account-Alpha");
  });
});
