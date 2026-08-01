# ADR-025 — Actor columns record an actor, not a user

**Status:** ACCEPTED (2026-08-01, `T-166`)
**Spec:** §12.2 (immutable actor attribution), §15.1, §17.5

## Decision

The columns that record *who did something* where that somebody may not be a person stay
`VARCHAR` and take **no foreign key**. They record an `Actor` — the `(type, id)` pair from
`audit_and_operations.service` — not a user:

| Column | Who can appear |
|---|---|
| `operational_flag.set_by` | a human administrator, or the system reconciling a flag |
| `record_version.created_by` | a human, or the process that published a prompt or schema version |
| `campaign_decision.decided_by` | a human reviewer, or an agent — `decided_by_type` is the discriminator |
| `user_session.revoked_by` | the session's own user, an administrator, or the system expiring it |
| `suppression.lifted_by` | a human only today, but §15.6 allows a policy source to lift one |
| `user_role.granted_by` | a human administrator, or the bootstrap that seeds the first roles |
| `service_identity_role.granted_by` | the same |

This is the answer `audit_event.actor_id` already has, and it now applies to the whole set rather
than to one column that happened to get written down.

**It does not apply to the approver columns.** `approval.approver_id` and the four `approved_by`
columns are foreign keys to `app_user.email` ([ADR-024](ADR-024-approver-columns-reference-a-user-by-email.md)),
because approving is something only a person may do — §12.1 gives approval authority to no service
and no schedule.

## Why

- **A foreign key would constrain the case that does not go wrong.** It could only cover the human
  branch. The failure worth preventing is a *system* actor written where a human was required —
  and a nullable key is satisfied by `NULL`, which is exactly that failure written down.
- **It would split "who did this" across two columns.** The key plus a discriminator has to be
  kept agreeing by application code, and this repository has twice deleted a rule enforced in two
  places for that reason (the duplicate scoped-key guard on the flag route, the duplicate
  verification check in `approve_message`). One string that an `Actor` produces has one writer.
- **The trail would still disagree with the row.** `audit_event.actor_id` stays a string whatever
  happens here — §12.2 requires the trail to outlive the user record — so keying these columns
  would leave the audit event and the row it describes in two different shapes.

## Rejected

- **Nullable foreign key to `app_user` plus a `*_type` discriminator**, the shape
  `campaign_decision` already half-uses. Rejected for the three reasons above. Revisit if a
  service identity ever needs the same referential guarantees a user has — `service_identity`
  exists as a table, and a key per actor *kind* would then be a different and better proposal
  than one nullable key pretending to cover both.
- **Making `Actor.id` a foreign key by making every actor a user row.** That would mean inventing
  a user called `dispatcher`, which §12.2 forbids in spirit: attribution has to say what actually
  acted, and a fake person is worse than an honest string.

## Known inconsistency, recorded not fixed

A human is written into these columns as `str(user.id)` — a UUID — because `Principal.actor`
produces it, while ADR-024 keys the approver columns on the **email**. Two vocabularies for one
concept: correlating an approval with the audit events around it needs a join nobody should have
to make. Filed as **`T-167`**; unifying them means touching every actor writer and is not this
decision's subject.

## Revisit when

`Q-026` names an identity provider and users acquire a stable `subject` (`T-061b`). If service
identities gain one too, "every actor is a row somewhere" becomes true for the first time and this
decision is worth re-opening.
