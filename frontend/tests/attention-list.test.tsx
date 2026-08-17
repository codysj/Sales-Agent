// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AttentionList } from "../app/attention/AttentionList";
import type { AttentionRow } from "../lib/api";
import { SESSION_TOKEN_KEY } from "../lib/session";

/**
 * Stale approvals on screen, and revoking one (T-068b; §7.5, §8.4, §17.6).
 *
 * The three criteria are about what a reviewer can *do next*. A list that says "this approval is
 * stale" and nothing else starts an investigation; the point of `T-068a` carrying `triggering_id`
 * is to end one. So the assertions are about the identifier being on screen, about the row leaving
 * the list once it is dealt with, and about a healthy queue looking healthy rather than empty.
 */

const TOKEN = "SYNTHETIC-session-token";
const CLAIM_SET_ID = "55555555-5555-4555-8555-555555555555";
const STATUS_VERSION_ID = "66666666-6666-4666-8666-666666666666";

function row(overrides: Partial<AttentionRow> = {}): AttentionRow {
  return {
    approval_id: "11111111-1111-4111-8111-111111111111",
    message_revision_id: "22222222-2222-4222-8222-222222222222",
    recipient_contact_point_id: "33333333-3333-4333-8333-333333333333",
    approver_id: "synthetic.reviewer@example.com",
    approval_expires_at: "2026-08-07T10:00:00Z",
    trigger: "claim_set_superseded",
    reason: "approved claim set has been superseded",
    triggering_id: CLAIM_SET_ID,
    record_version: "2026-07-31T10:00:00Z",
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

function revoked(approvalId: string) {
  return { approval_id: approvalId, state: "revoked", reason: "SYNTHETIC", record_version: "x" };
}

function type(approvalId: string, reason: string) {
  fireEvent.change(screen.getByLabelText("Why are you revoking this?", { selector: `#reason-${approvalId}` }), {
    target: { value: reason },
  });
}

function revoke(approvalId: string) {
  fireEvent.submit(screen.getByRole("form", { name: `Revoke approval ${approvalId}` }));
}

beforeEach(() => {
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, TOKEN);
});

afterEach(() => {
  cleanup();
  window.sessionStorage.clear();
  vi.unstubAllGlobals();
});

// --- criterion 1: an invalidated approval appears with its triggering version --------------------

describe("a stale approval", () => {
  it("shows the record that made it stale, not only the category", () => {
    render(<AttentionList rows={[row()]} />);

    const item = screen.getByRole("listitem").textContent ?? "";
    expect(item).toContain("Approved claim set");
    expect(item).toContain(CLAIM_SET_ID);
  });

  it("labels the triggering record by what it is for each trigger", () => {
    // The identifier alone is a UUID with no noun attached. `product_status_superseded` and
    // `claim_set_superseded` point at different tables, and a reviewer chasing one needs to know
    // which.
    render(<AttentionList rows={[row({ trigger: "product_status_superseded", triggering_id: STATUS_VERSION_ID })]} />);

    const item = screen.getByRole("listitem").textContent ?? "";
    expect(item).toContain("Product status version");
    expect(item).toContain(STATUS_VERSION_ID);
    expect(item).not.toContain("Approved claim set");
  });

  it("tells a reviewer what to do about an approval that cannot prove its currency", () => {
    // ADR-029. This trigger is unlike the others: nothing changed, the approval simply
    // does not record what it was granted against, so there is no record to chase. The
    // row has to say what to *do* — the reviewer's next action is not obvious from the
    // trigger name the way `content_changed` makes it obvious.
    render(
      <AttentionList
        rows={[row({ trigger: "currency_unverifiable", triggering_id: null })]}
      />,
    );

    const item = screen.getByRole("listitem").textContent ?? "";
    expect(item).toContain("Revoke it and approve again");
    expect(item).not.toContain("Product status version");
  });

  it("says a trigger names no other record rather than rendering a blank", () => {
    // "Nothing else is involved" and "we failed to load it" are the same empty cell, and they
    // need different reactions.
    render(<AttentionList rows={[row({ trigger: "expired", triggering_id: null })]} />);

    const item = screen.getByRole("listitem").textContent ?? "";
    expect(item).toContain("None — this is a fact about the approval itself");
    expect(item).not.toContain(CLAIM_SET_ID);
  });

  it("carries the backend's own reason as well as the explanation", () => {
    render(<AttentionList rows={[row()]} />);

    expect(screen.getByRole("listitem").textContent).toContain(
      "approved claim set has been superseded",
    );
  });
});

// --- criterion 2: revoking from the list removes it -----------------------------------------------

describe("revoking", () => {
  it("needs a reason before it can be submitted", () => {
    render(<AttentionList rows={[row()]} />);

    const button = screen.getByRole<HTMLButtonElement>("button", { name: "Revoke" });
    expect(button.disabled).toBe(true);

    type(row().approval_id, "no longer relevant");

    expect(screen.getByRole<HTMLButtonElement>("button", { name: "Revoke" }).disabled).toBe(false);
  });

  it("sends nothing when submitted with a blank reason", () => {
    const stub = stubFetch(revoked(row().approval_id));
    render(<AttentionList rows={[row()]} />);

    type(row().approval_id, "   ");
    revoke(row().approval_id);

    expect(stub).not.toHaveBeenCalled();
  });

  it("sends the reason, the record version, and the bearer token", async () => {
    const stub = stubFetch(revoked(row().approval_id));
    render(<AttentionList rows={[row()]} />);

    type(row().approval_id, "the claim was withdrawn");
    revoke(row().approval_id);

    await waitFor(() => {
      expect(stub).toHaveBeenCalled();
    });
    const init = stub.mock.calls[0]?.[1];
    const body = init?.body;
    if (typeof body !== "string") {
      throw new Error("the revocation carried no JSON body");
    }
    expect(JSON.parse(body)).toMatchObject({
      reason: "the claim was withdrawn",
      record_version: "2026-07-31T10:00:00Z",
    });
    expect((init?.headers as Record<string, string>)["authorization"]).toBe(`Bearer ${TOKEN}`);
  });

  it("removes the row it revoked, and only that row", async () => {
    const other = row({
      approval_id: "44444444-4444-4444-8444-444444444444",
      trigger: "content_changed",
    });
    stubFetch(revoked(row().approval_id));
    render(<AttentionList rows={[row(), other]} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(2);

    type(row().approval_id, "superseded by a newer draft");
    revoke(row().approval_id);

    await waitFor(() => {
      expect(screen.getAllByRole("listitem")).toHaveLength(1);
    });
    // The survivor is the *other* one — a list that dropped the wrong row would also have gone
    // from two items to one.
    expect(screen.getByRole("form", { name: `Revoke approval ${other.approval_id}` })).toBeTruthy();
  });

  it("keeps the row and shows the backend's refusal when it is refused", async () => {
    stubFetch(
      {
        detail:
          "this approval changed since it was loaded; reload before revoking so you are acting " +
          "on the state you read",
      },
      409,
    );
    render(<AttentionList rows={[row()]} />);

    type(row().approval_id, "no longer relevant");
    revoke(row().approval_id);

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("reload before revoking");
    });
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });

  it("refuses to send at all when there is no session", async () => {
    window.sessionStorage.clear();
    const stub = stubFetch(revoked(row().approval_id));
    render(<AttentionList rows={[row()]} />);

    type(row().approval_id, "no longer relevant");
    revoke(row().approval_id);

    await waitFor(() => {
      expect(screen.getByRole("alert").textContent).toContain("not signed in");
    });
    expect(stub).not.toHaveBeenCalled();
    expect(screen.getAllByRole("listitem")).toHaveLength(1);
  });
});

// --- criterion 3: a healthy approval is not shown as needing attention ---------------------------

describe("a queue with nothing stale", () => {
  it("says so rather than rendering an empty list", () => {
    // The endpoint returns only approvals that no longer authorize a send (`T-068a`'s
    // `test_a_valid_approval_is_not_listed`), so "still authorizes a send" reaches this component
    // as absence. An empty page would read as "not loaded".
    render(<AttentionList rows={[]} />);

    expect(screen.queryByRole("list", { name: "Stale approvals" })).toBeNull();
    expect(screen.getByText(/No approval needs attention/)).toBeTruthy();
  });

  it("claims nothing about the rest of the page", () => {
    // `T-209`. This used to read "Nothing needs attention" — a claim about the whole page, made
    // by the half of it that can only see approvals. `T-071d` watched it say exactly that while a
    // candidate's only draft could be approved by nobody.
    render(<AttentionList rows={[]} />);

    expect(screen.queryByText(/Nothing needs attention/)).toBeNull();
  });

  it("offers no revoke control when nothing is stale", () => {
    render(<AttentionList rows={[]} />);

    expect(screen.queryByRole("button", { name: "Revoke" })).toBeNull();
  });

  it("is what remains after the last stale approval is revoked", async () => {
    stubFetch(revoked(row().approval_id));
    render(<AttentionList rows={[row()]} />);

    type(row().approval_id, "handled");
    revoke(row().approval_id);

    await waitFor(() => {
      expect(screen.getByText(/No approval needs attention/)).toBeTruthy();
    });
    expect(screen.queryByRole("listitem")).toBeNull();
  });
});
