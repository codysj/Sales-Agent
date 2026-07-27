"""Audit trail, operational controls, and versioning (specification §3.5, §17.5, §17.6, §14.1).

Owns the append-only ``AuditEvent`` (no update or delete path), the operational flags from §17.6
— global pause, campaign pause, shadow mode, outbound-email disable, product/claim-version
disable — and the ``PromptVersion`` / ``SchemaVersion`` / ``ModelConfigVersion`` / ``PolicyVersion``
records that make every decision attributable to exact versions.

This is the one platform module every other module may depend on: every consequential action must
carry an actor, a revision, a policy decision, and an audit event (§3.5).

Must not own: business rules belonging to any single domain. It records and gates; it does not
decide what a good candidate is.
"""
