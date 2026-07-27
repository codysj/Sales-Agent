"""Database access.

PostgreSQL holds authoritative workflow state, job leases, and the transactional outbox
(specification ADR-003, §17.1, §17.2). Schema definition and migrations arrive with T-006.
"""
