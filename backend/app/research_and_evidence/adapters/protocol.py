"""The §9.5 source-adapter contract (T-046).

§9.5 states it as:

```text
discover(criteria) -> Candidate[]
import(record | url | file) -> Candidate[]
refresh(candidate_id) -> EvidenceSnapshot[]
```

This module names all three, because a capability that is absent from the interface is a
capability nobody can see is missing. Two of them refuse: `discover` needs a provider `Q-003` has
not chosen and gate **G-03**; `import_records` is implemented for CSV by `T-042` in `prospects`,
where prospect identity belongs, and a second import path here would be a second place for the
same rule to drift. Both raise `SourceCapabilityUnavailable` naming the gate — a refusal an
operator can read, not a silent empty list.

**Two deliberate divergences from the literal §9.5 signature**, recorded as `R-004`:

* `refresh` takes the account's normalized domain rather than a `candidate_id`. An adapter has no
  database session, so resolving a candidate to the thing a source can actually be looked up by is
  the application's job, not the adapter's.
* `refresh` returns `CapturedFact`, not `EvidenceSnapshot`. An adapter that built ORM rows would
  own persistence, provenance defaults, and the candidate association — all of which belong to
  `capture.py`, so that one place decides what a snapshot records.

`import` is spelled `import_records` because `import` is a keyword.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.research_and_evidence.models import (
    ExtractionMethod,
    RetentionClass,
    SourceQuality,
    SourceType,
)


class SourceCapabilityUnavailable(Exception):
    """The adapter refuses a capability that is gated or belongs elsewhere.

    Raised rather than returning nothing: an empty result reads as "the source had nothing to
    say", which is a very different claim from "this capability does not exist yet".
    """


@dataclass(frozen=True, slots=True)
class CapturedFact:
    """One fact an adapter found, with the provenance §14.3 requires to explain it later.

    Everything here is untrusted data (§15.4). `excerpt` is text a document contained; nothing
    reads it as an instruction, and `capture.py` stores it verbatim.
    """

    #: The document the fact came from, as the source names it. Not a URL.
    source_document_id: str
    source_type: SourceType
    excerpt: str
    #: SHA-256 of the whole source content, so a later refresh can tell "changed" from "same".
    content_hash: str
    extraction_method: ExtractionMethod
    source_quality: SourceQuality
    retention_class: RetentionClass
    #: No default. An unanswered privacy classification must never become "contains nothing"
    #: (§15.5, `Q-019`).
    contains_personal_or_confidential_data: bool
    extraction_field_or_span: str | None = None
    #: Only where the source's terms permit storing it (§9.5).
    source_url_if_permitted: str | None = None
    expires_or_refresh_by: datetime | None = None
    #: Free-form provenance the adapter wants preserved. Never instructions.
    notes: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class SourceAdapter(Protocol):
    """What every source must offer. Only `FixtureSourceAdapter` implements it in Stage 1."""

    #: Stable identifier recorded on every snapshot this adapter produces.
    name: str

    def discover(self, criteria: dict[str, str]) -> Sequence[str]:
        """§9.5 `discover(criteria)`. Gated behind `Q-003` and **G-03**."""
        ...

    def import_records(self, reference: str) -> Sequence[str]:
        """§9.5 `import(record | url | file)`. CSV import is `T-042`, in `prospects`."""
        ...

    def refresh(self, *, account_domain: str) -> Sequence[CapturedFact]:
        """§9.5 `refresh`. Returns facts; `capture.py` turns them into snapshots."""
        ...
