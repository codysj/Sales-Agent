"""Identity and access (specification §14.1, §12.1, §12.2).

Owns ``User``, ``Role``, ``UserRole``, ``ServiceIdentity``, ``ChannelIdentity``; the six roles
from §12.1; managed OIDC/SSO session handling; and server-side authorization checks. Human and
service identities stay distinct, and a channel identity is only ever a mapping onto an existing
application user.

Must not own: any workflow state, product decision, or approval semantics — it answers *who is
acting and may they*, never *what happens next*. It never implements password authentication
(§12.2 rejects it).
"""
