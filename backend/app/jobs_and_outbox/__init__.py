"""Job queue and transactional outbox (specification §17.1, §17.2, ADR-003, ADR-016).

Owns the ``Job`` table with ``FOR UPDATE SKIP LOCKED`` leasing, per-job-type retry policy with
backoff, dead-lettering with a human-readable reason, lease-expiry recovery, ``OutboxEvent``, and
the atomic ``state + audit + outbox`` commit helper. This is **generic mechanism**: it moves work
and guarantees delivery semantics.

Must not own: any domain rule. It knows job *types* and typed payloads, not what a candidate or a
claim is — domain modules register handlers and perform their own rechecks inside the dispatch
transaction. Enforced by ``tests/test_module_boundaries.py``: this package imports no domain
module.
"""
