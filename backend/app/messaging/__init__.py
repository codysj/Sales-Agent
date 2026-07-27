"""Channel-neutral messaging gateway (specification §12.4, §12.5, §15.2, ADR-006).

Owns webhook signature, timestamp, and replay verification; channel-identity to application-user
mapping; the provider-neutral notification and bounded-command contract; and short-lived
action-specific links that open the authenticated dashboard. WhatsApp is the intended first
channel and iMessage a possible second, both behind gate **G-04**; neither may become the sole
production channel.

Must not own: approval authority — "yes", an emoji, or any ambiguous reply is never an approval —
and it must never become a dependency of background jobs or recovery. The dashboard stays
authoritative (ADR-006). Enforced by ``tests/test_module_boundaries.py``: no domain imports.
"""
