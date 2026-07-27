"""Outreach execution and reply handling (specification §8.2, §11.4, §17.3, ADR-016).

Owns ``OutreachThread``, the immutable ``SendCommand`` carrying the full §11.4 field list and its
idempotency key, ``SendAttempt``, ``DeliveryEvent``, ``Interaction``, and the final dispatch-time
rechecks. Effectively-once semantics: an ambiguous provider response becomes ``delivery_unknown``
and is reconciled, never blindly retried. Any reply stops automated sequencing.

Must not own: the decision that a send is authorized (``drafts_and_approvals`` owns approval), nor
the transport itself (the email adapter is provider-specific and, until gate **G-07**, fake).
"""
