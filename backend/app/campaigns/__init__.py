"""Campaigns and campaign membership (specification §8.1, §8.6, §14.1, ADR-012).

Owns ``Campaign``, ``TargetSegment``, ``CampaignPolicyVersion``, and ``CampaignCandidate``.
Qualification belongs to a membership, not to a company: the effective identity is
``campaign_id + account_id + contact_id``, so one account may be evaluated independently for the
sodium-battery and DC-fast-charging campaigns. Policy is versioned and immutable once referenced.

Must not own: prospect identity or deduplication (``prospects``), evidence, scoring, or draft
content. It decides *which campaign a candidate belongs to*, never *whether they are any good*.
"""
