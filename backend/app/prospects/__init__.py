"""Prospect identity and suppression (specification §14.1, §13.5, §15.6).

Owns ``Account``, ``Contact``, ``ContactPoint``, ``CRMMapping``, and ``Suppression``; identity
normalization; deterministic deduplication; and CSV/manual import. Suppression is stronger than
ordinary state: it outranks campaign policy, survives contact deletion, and applies immediately
across active campaigns.

Must not own: calls to any CRM provider (``crm`` holds the adapter), campaign eligibility
decisions (``qualification``), or evidence.
"""
