"""Source adapters — the §9.5 contract and the only implementation Stage 1 permits.

One adapter exists: `FixtureSourceAdapter`, which reads local synthetic documents from a
directory. There is no HTTP client here and there must not be one — §15.3 requires SSRF
protection, redirect and size limits, and isolated document parsing for any fetch path, and none
of that has been built or reviewed. Gate **G-03** and `Q-003` govern when it may be.

`tests/test_evidence_capture.py` asserts that nothing under `research_and_evidence` imports an
HTTP client, so this is enforced rather than intended.
"""

from app.research_and_evidence.adapters.protocol import (
    CapturedFact,
    SourceAdapter,
    SourceCapabilityUnavailable,
)

__all__ = ["CapturedFact", "SourceAdapter", "SourceCapabilityUnavailable"]
