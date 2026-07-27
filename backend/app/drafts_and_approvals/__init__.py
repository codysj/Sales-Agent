"""Drafts, immutable revisions, and approvals (specification §10.5, §8.4, §11.3, ADR-008).

Owns ``MessageDraft``, the strictly immutable ``MessageRevision`` chain, revision validation, and
the ``Approval`` lifecycle including expiry, revocation, and supersession. Every product sentence
resolves to a current approved claim ID and every prospect fact to a stored evidence ID, or
validation fails. Editing creates revision N+1 and invalidates any prior approval. An approval
binds exactly one approver, one recipient, and one immutable revision.

Must not own: execution of a send (``outreach_and_replies`` plus the outbox), or any mutation of
product claims. Approval is a human act recorded here; no model or agent may perform it.
"""
