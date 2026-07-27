"""Product knowledge and approved claims (specification §2.3, §10.5, §14.4, §15.7, GP-12).

Owns ``Product``, ``ProductStatusVersion``, ``ApprovedClaim``, ``ApprovedClaimSet``,
``SourceDocument``; the five readiness categories; claim validity windows, campaign scoping,
supersession; and the invalidation job that fires when a status or claim version changes. Claim
resolution fails closed: an expired or superseded claim raises rather than being filtered away.

Must not own: outbound copy generation (that is ``drafts_and_approvals``), campaign membership,
or any judgement about a prospect. Internal source material is never an approved claim until it
appears here as a versioned, approved record.
"""
