"""Eligibility and qualification (specification §10.1 to §10.4, §8.5, §10.6).

Owns the two stages kept deliberately apart: deterministic **hard eligibility** (geography,
exclusions, suppression, product readiness, contactability, relationship conflicts) and the
model-supported **ranked rubric** that produces the §10.4 structured output — opportunity type,
dimension scores, evidence completeness, ambiguities, risks. Also owns ``QualificationRun`` and
structured human correction reasons.

Must not own: draft copy (``drafts_and_approvals``) or any approval. A model recommendation can
never overturn a failed hard rule, and model self-reported confidence controls nothing.
"""
