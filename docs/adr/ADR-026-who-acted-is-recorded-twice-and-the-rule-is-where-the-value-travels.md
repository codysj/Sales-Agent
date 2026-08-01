# ADR-026 — Who acted is recorded twice, and the rule is where the value travels

**Status:** ACCEPTED (2026-08-01, `T-167`)
**Spec:** §12.2 (immutable actor attribution), §15.5 (redact contacts from logs), §17.5

## Decision

A human is recorded two ways, deliberately, and which one to use is decided by **where the value
travels**, not by which table it lands in:

| Vocabulary | Value | Used by | Because |
|---|---|---|---|
| **Actor** | `str(user.id)` — a UUID | `audit_event.actor_id` and every column [ADR-025](ADR-025-actor-columns-record-an-actor-not-a-user.md) governs | it flows into the audit trail and is the value most likely to be logged, exported, or handed to an operator |
| **Approver** | `user.email` | `approval.approver_id` and the four `approved_by` columns ([ADR-024](ADR-024-approver-columns-reference-a-user-by-email.md)) | it is a narrow business record a reviewer reads on screen, and a foreign key makes it unambiguous |

`Principal.actor` produces the first. The review API writes the second. Neither may be used in the
other's place.

## Why not one vocabulary

**Unifying on the email was the tempting answer and is the unsafe one.** It would make `Actor.id`
a contact address — and the actor is exactly the field that ends up in log lines. §15.5 asks for
contacts to be redacted from logs; today `campaigns/approval.py` logs `actor_type=actor.type.value`
and never the id, which is only safe *because* the id is opaque. Making it an address turns every
future `log.info(..., actor_id=actor.id)` — a natural thing for the next person to write — into a
violation nobody would notice. A rule that depends on everyone remembering is not a rule.

**Unifying on the UUID would make the reviewer's screen unreadable and contradict a decision one
cycle old.** The five approver columns are keyed on `app_user.email`; moving them to the id means
a migration, and an approval that says `9b47ff3d-…` instead of a name is worse for the person who
has to check it. ADR-024's reasoning has not changed.

So the two exist for opposite reasons, and that is the finding: the split is not an accident, it
just was not written down. What was actually missing is the **rule** and something holding each
side to it.

## Consequences

- Correlating an approval with the audit events around it needs a join through `app_user`. That
  cost is accepted, and it is one join.
- `tests/test_actor_columns.py` pins both sides: `Principal.actor.id` must parse as a UUID and
  must not be an address, and the approver columns must hold something that resolves to
  `app_user.email`. Either side drifting into the other's vocabulary fails.
- Any new column recording who acted picks a vocabulary by asking where the value travels, and
  says which one it picked next to the column, as ADR-025 requires.

## Rejected

- **Storing both** (a UUID column plus a denormalized email). Two columns that must agree, kept
  agreeing by application code — the shape this repository has now deleted three times.
- **Making `Actor.id` opaque everywhere and rendering the email only in the API layer.** This is
  what already happens for the audit trail; extending it to the approver columns would drop the
  foreign key that stops an approver being a typo, which is the whole of `T-136`.

## Revisit when

`Q-026` names an identity provider and users acquire a stable `subject` (`T-061b`). A provider
subject is opaque *and* durable, which is the only value that could honestly serve both roles.
