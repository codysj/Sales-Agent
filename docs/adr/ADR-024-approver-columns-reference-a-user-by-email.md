# ADR-024 — Approver columns reference a user by email, not by id

**Status:** ACCEPTED (2026-08-01, `T-136b`)
**Spec:** §14.4 (`approved_by`), §12.2 (immutable actor attribution), §15.1

## Decision

`product_status_version.approved_by`, `approved_claim.approved_by`, `approved_claim_set.approved_by`,
and `campaign_policy_version.approved_by` are foreign keys to **`app_user.email`**, with
`ON DELETE RESTRICT` and `ON UPDATE CASCADE`. The column keeps its `VARCHAR(255)` type and its
existing values.

## Why

`T-136` asked for foreign keys "so an approver cannot be a typo and cannot be deleted out from
under the record that depends on them". Both goals are met by a key on any unique column, and
`app_user.email` is already `UNIQUE NOT NULL`.

Choosing the email over the id buys three things:

- **The row still says who, without a join.** That is the same reason `audit_event.actor_id` stays
  a readable string — a trail nobody can read during an incident is a trail nobody reads.
- **It matches what the application already writes.** The review API records
  `principal.user.email`; a UUID column would have required changing every writer as well as every
  column, in the same change set that adds the constraint.
- **`T-136c` stays simple.** §11.4 compares `approval.approver_id` against the value copied into
  `send_command.record_versions["approver_id"]`, which is JSON. String-to-string keeps that
  comparison as it is; a UUID on one side and JSON text on the other is a bug waiting for a
  migration to introduce it.

`ON UPDATE CASCADE` is the price: an email is a natural key, and a corrected address must follow
the rows that cite it rather than orphan them.

## Rejected

- **A `UUID` foreign key to `app_user.id`.** The textbook answer, and it is what `T-136`'s wording
  implies. Rejected here because every one of the reasons above would have to be paid for
  separately, and because none of the three named goals — no typos, no deleted approvers, one
  place that decides who an approver is — needs a surrogate key to hold. Revisit if an approver's
  email ever has to change frequently, or if a second identity provider makes the email
  non-unique across sources.
- **Leaving the columns as free text and validating in the application.** That is what was already
  happening, and `T-136a` found the result: three vocabularies for one concept and no value that
  resolved to anything.
- **Nulling unresolvable approvers in the migration** so it never fails. Rejected outright: §12.2
  requires attribution to be immutable, and deleting an approver to make a schema change
  convenient is exactly the thing that clause forbids. The migration refuses and names the rows.

## Revisit when

An identity provider lands (`Q-026`, `T-061b`) and users acquire a stable `subject`. If the
provider's identifier becomes the durable one, the key should move to it — and `ON UPDATE CASCADE`
is what makes that migration a rename rather than a rewrite.
