# ADR-023 — An approval without a current claim set is refused

- **Status:** ACCEPTED (2026-07-31)
- **Scope:** Local to this repository. Does not modify any inherited specification ADR.
- **Specification basis:** §11.4 lists `product_status_version` and `approved_claim_set_version`
  among the fields **every** consequential action contains. §8.4 makes a changed product status or
  claim version invalidate an approval. §10.5 requires every outbound product statement to cite a
  current approved claim.
- **Found by:** `T-157`, itself found by the 2026-07-31 checkpoint audit of `T-067a`'s output.
- **Implemented by:** `T-157`.

## Context

The §11.3 transaction created approvals that pinned neither version, and `invalidation_detail`
checks each pin only `if ... is not None`. Two of §8.4's six triggers could therefore never fire on
any approval the production path produced.

Resolving the product status version at approval time is unambiguous: `get_effective_status` returns
exactly one row or none, and `T-055`'s validation has already refused the revision if there is none.

The claim set is the discretionary part. A campaign may have approved claims linked to it (§14.4's
allow-list) without anyone having *published a set* — `publish_claim_set` is a separate act, and
nothing before this task required one to exist before a message could be approved. So the
specification leaves a gap: what should the transaction pin when there is no current set?

## Decision

**No current approved claim set means the approval is refused.** The transaction fails closed rather
than pinning null.

The refusal is `ApprovalTransactionRefused`, which the endpoint already maps to `409`, naming the
campaign and product so an administrator knows what to publish.

## Alternatives rejected

**Pin null when there is no set.** This is what the code did before, and it is the defect: an
approval with a null pin is one §8.4 can never invalidate, and a send command carrying null in a
field §11.4 lists as mandatory is an action nobody can later recheck. It also fails silently — the
approval looks perfectly valid right up to the moment the claims change underneath it.

**Synthesise a set from the claims the revision cites.** It would produce a set nobody approved. The
set is the unit of approval (§10.5); assembling one at approval time from whatever happens to be
current makes the application, not a human, the thing that decided which claims were in it.

**Pin only the product status and leave the claim set optional.** Half the fix. It would close one
§8.4 trigger and leave the other exactly as dead as it was, with nothing in the code recording that
the second one was knowingly left broken.

## Consequences

- A campaign must have a published claim set before any message in it can be approved. The synthetic
  fixtures already publish one (`app/fixtures/synthetic.py`); a campaign configured by hand needs
  `publish_claim_set` first.
- The two §8.4 triggers become live for every approval, so the §7.5 attention queue will now surface
  approvals it previously showed as healthy.
- Superseding a claim set invalidates every approval pinned to it, including ones already granted.
  That is §8.4 working as specified, and it is why the attention queue exists.
