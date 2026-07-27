"""CRM adapter (specification §13.2 to §13.5, ADR-004).

Owns the §13.5 adapter contract, a ``FakeCRMAdapter`` for tests, the internal shadow-mode
repository, and — only if `Q-001` is answered yes and gate **G-05** opens — a ``HubSpotAdapter``.
Synchronization is deliberately asymmetric: read existing accounts, contacts, owners, and
suppressions; write only approved contacts and customer-facing activity. Writes are idempotent
through the external-ID mapping.

Must not own: internal model runs, evidence, approvals, or job state (§5.1). No production
``NoCRMAdapter`` that quietly grows into a second CRM (ADR-004). Enforced by
``tests/test_module_boundaries.py``.
"""
