# ADR-029 — An approval that cannot prove its currency does not authorize a send

**Status:** ACCEPTED (2026-08-01, `T-193b`) — decided and applied by the loop. It reverses an
interpretation that existed only in a test docstring and was never recorded anywhere a reader
would find it, which is why it gets a record rather than a commit message.
**Spec:** §8.4, §11.4

## The problem

`invalidation_detail` guarded both §8.4 currency checks with `if approval.<pin> is not None:`. An
approval missing either `product_status_version_id` or `approved_claim_set_id` therefore **skipped**
the check and read as still valid. It failed **open** on missing information.

The 2026-07-31 checkpoint's HIGH finding `H1` was the other half of this: the production path was
not setting the pins at all, so *every* approval it created skipped both checks. `T-157` fixed the
caller and `T-193a` pinned it with an AST walk. What remained was the question this record answers:
what should a null pin *mean*?

## What the specification says

§11.4 lists what every external action carries, without qualification:

> Every external action contains: … `product_status_version` `approved_claim_set_version` …

and lists among the final dispatch transaction's rechecks:

> Product-status and approved-claim versions.

§8.4 makes the underlying facts invalidating:

> A changed recipient, subject, body, material personalization fact, product status, or claim
> version invalidates the approval.

A recheck that cannot run is not a recheck. If the pins are absent, the §11.4 recheck has nothing
to compare and the §8.4 condition cannot be evaluated — so the honest answer is not "then it is
fine", it is "then this cannot be shown to be safe".

## The interpretation being reversed

`tests/test_preconditions.py` carried a test named
`test_a_command_citing_no_product_status_is_not_refused_for_it`, whose docstring read:

> Not every effect makes a product claim, and §11.4 allows the field's absence.

That is a defensible engineering thought and it is **not** what §11.4 says. More to the point, it
was recorded nowhere — not in `docs/reconciliation.md`, not in an ADR, not in the ledger. A
permissive reading of a safety clause that lives only in a test docstring is exactly the kind of
decision this repository writes down.

## Decision

`invalidation_detail` returns an `Invalidation` with a new trigger, `currency_unverifiable`, when
either pin is null. The approval does not authorize a send.

**In practice the refusal lands earlier than dispatch**, which is more than the contract asks for
and was found by testing rather than designed: `create_send_command` calls `require_valid_approval`,
so an approval that cannot prove its currency never becomes a send order in the first place. The
`/attention` list shows it to a reviewer under the same trigger.

The reason field says why in a sentence a reviewer can act on: the approval does not record which
product status version and approved claim set it was granted against, so §8.4's currency checks
cannot be run against it.

## What this costs, honestly

- **Nothing operationally.** `app/outreach_and_replies/approve_message.py` is the only production
  caller of `request_approval` and it sets both pins — verified, and now enforced by
  `tests/test_invariants.py::test_every_production_approval_pins_both_versions` (`T-193a`). No
  approval the system creates is affected.
- **A shared-fixture change.** `tests/factories.py` built unpinned approvals, so 66 tests failed
  the moment the check began firing. They were not wrong about the system; they were building an
  approval the production path cannot produce. `World.approval()` now pins by default, with
  `pinned=False` for the tests that want the refusal itself.

## Rejected

- **Leave it open, and record the permissive reading instead.** It would mean writing down that a
  send may go out whose product-status currency nobody can establish, in a system whose entire
  posture is fail-closed. If §11.4's field list is genuinely meant to be optional, that is a
  specification change for the user to make, not an inference for the loop to bank.
- **Make the columns `NOT NULL` and the parameters required.** Stronger — the state could not
  exist — but it needs a migration and a backfill decision for rows already written, and it is not
  necessary for the safety property: after this change a null-pin approval is inert, because it can
  never authorize a send. Worth revisiting if the state proves to have no legitimate use at all.

## Revisit when

An external action type exists that genuinely makes no product claim — a plain reply, say. At that
point the question is real rather than theoretical, and the answer may be that such an action does
not carry an approval of this shape at all. `§11.4`'s list would then want re-reading with the user.
