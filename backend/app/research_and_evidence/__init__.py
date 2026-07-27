"""Research and evidence capture (specification §9.5, §14.3, GP-02).

Owns ``EvidenceSnapshot``, the source-adapter contract (``discover`` / ``import`` / ``refresh``),
capture jobs, provenance, retention and license classification, and the normalization of untrusted
external text into typed facts before it reaches any prompt (§15.4). Stores the minimum evidence
needed to explain a decision — never whole third-party documents. ``refresh`` writes a new snapshot
rather than mutating one.

Must not own: interpretation of evidence into a recommendation (``qualification``), or fetching
from any source that is not approved. Until gate **G-03**, capture reads local fixtures only and
no HTTP client may exist in this package.
"""
