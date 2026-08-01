"""Turning stored evidence into typed facts (T-057; §15.4, §0 item 8, §19.4).

§15.4: "Normalize external text into typed facts before including it in higher-authority prompts
where practical." This is that normalization. A prompt should be shown

    field=summary  evidence=6b1f…  value="the account is evaluating storage"

rather than a paragraph of prose that happens to have arrived from a third party. The difference
is not cosmetic: a typed record has a field name, a source ID, and a bounded value, so the prompt
can present it as *a datum someone recorded* instead of as text that looks exactly like the
instructions around it.

**Normalization never rewrites words.** It strips characters that carry no meaning and exist
mainly to deceive — C0/C1 control codes, zero-width joiners and spaces, and the Unicode
bidirectional overrides that can make a line render as something other than what it says — then
collapses whitespace and caps length. Removing *content* would be worse than useless: it would
give a false sense that the text had been made safe, and it would corrupt evidence a reviewer
must be able to compare against the source (`T-046` stores excerpts verbatim, and this does not
change what is stored).

`NormalizedFact` itself is defined in `model_gateway.prompt_assembly`, not here: it is the
prompt's input contract, and §5.1 forbids `model_gateway` from importing a domain module. This
module produces them and re-exports the name so callers have one import to reach for.

**It is not a sanitizer and does not claim to be.** No filter reliably detects an instruction
written in prose. The guarantee this module contributes is structural — every fact carries the
evidence ID it came from, so anything a prompt shows can be traced — and the containment
guarantee belongs to `model_gateway.prompt_assembly`, which keeps this text inside a delimited
data section. Whether a real model then obeys an instruction it was told to treat as data is
`T-083`'s adversarial suite, not something this file can assert.
"""

import re
import unicodedata
from collections.abc import Sequence
from typing import Final

from app.model_gateway.prompt_assembly import NormalizedFact
from app.research_and_evidence.models import EvidenceSnapshot

__all__ = [
    "DEFAULT_FIELD",
    "TRUNCATION_MARKER",
    "VALUE_MAX_CHARS",
    "NormalizedFact",
    "normalize_snapshot",
    "normalize_snapshots",
    "normalize_value",
    "strip_invisible",
]

#: Field name used when a snapshot records no extraction field of its own.
DEFAULT_FIELD: Final = "excerpt"

#: Values longer than this are truncated *with a visible marker*, so a reviewer can tell. The cap
#: is well above `EXCERPT_MAX_CHARS`, so it only fires on something unusual.
VALUE_MAX_CHARS: Final = 1200

TRUNCATION_MARKER: Final = " …[truncated]"

#: Characters removed outright. Each is invisible or reorders rendering, and none of them carries
#: meaning a reviewer would miss:
#:   * `Cc` — C0/C1 control codes, including the ANSI escapes that can rewrite a terminal line.
#:   * `Cf` — format characters: zero-width space/joiner, and the bidi overrides (U+202A…U+202E,
#:     U+2066…U+2069) that make text render in an order other than the one it is stored in.
#: Newlines and tabs are `Cc` too, so they are replaced by a space rather than deleted.
_INVISIBLE_CATEGORIES: Final = frozenset({"Cc", "Cf"})
_WHITESPACE = re.compile(r"\s+")


def strip_invisible(text: str) -> str:
    """Remove control and format characters, keeping every visible character.

    Whitespace-ish controls become a space so words do not run together; everything else in the
    two categories is dropped. Nothing readable is removed, so a reviewer comparing this against
    the stored excerpt sees the same words in the same order.
    """
    kept: list[str] = []
    for character in text:
        category = unicodedata.category(character)
        if category not in _INVISIBLE_CATEGORIES:
            kept.append(character)
        elif character in "\t\n\r\v\f":
            kept.append(" ")
    return "".join(kept)


def normalize_value(text: str) -> str:
    """Strip invisibles, collapse whitespace, and cap length. Words are never removed."""
    cleaned = _WHITESPACE.sub(" ", strip_invisible(text)).strip()
    if len(cleaned) <= VALUE_MAX_CHARS:
        return cleaned
    # Marked, not silent: a reviewer must be able to tell that they are not seeing all of it.
    return cleaned[:VALUE_MAX_CHARS] + TRUNCATION_MARKER


def normalize_snapshot(snapshot: EvidenceSnapshot) -> NormalizedFact:
    """One stored snapshot as one typed fact."""
    return NormalizedFact(
        field=(snapshot.extraction_field_or_span or DEFAULT_FIELD).strip() or DEFAULT_FIELD,
        value=normalize_value(snapshot.supporting_excerpt_or_fact),
        source_evidence_id=snapshot.id,
    )


def normalize_snapshots(snapshots: Sequence[EvidenceSnapshot]) -> list[NormalizedFact]:
    """Typed facts for a candidate's evidence, in the order given.

    Order is the caller's — `current_evidence` returns newest first — and is preserved rather than
    re-sorted, so two runs over the same evidence produce the same prompt (`T-052`).
    """
    return [normalize_snapshot(snapshot) for snapshot in snapshots]
