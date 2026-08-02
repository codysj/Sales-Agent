"""The specification is unmodified, and the claim is checked rather than asserted (T-192; §22).

The specification is the **user's** source document, placed in `docs/` on 2026-07-27. This
repository asserts in two binding files that the loop has not touched it, by recording its
SHA-256 and byte size — `tasks.md` row 10, `tasks.md`'s `T-001` completion evidence, and
`AGENTS.md`. Until `T-192` nothing recomputed either number, so the assertion was a sentence:

* a loop invocation that edited the specification would leave every recorded hash wrong and the
  suite green — and `T-183` is `BLOCKED` on user authorisation precisely because editing it
  "breaks a recorded integrity property on purpose";
* a hash updated in one document and not the other would leave two binding files disagreeing
  about whether the source has changed.

**Nothing here restates the digest.** It is read out of the documents that record it; a copy in
this file would be a sixth, and a sixth copy is the defect, not the check. What the tests below
own instead is that the readers matched something — a reader that quietly finds nothing turns
every assertion after it into a tautology.

Offline: this hashes one local file and reads two others.
"""

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPECIFICATION = REPO_ROOT / "docs" / "MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md"
LEDGER = REPO_ROOT / "tasks.md"
AGENTS = REPO_ROOT / "AGENTS.md"

#: Any uppercase SHA-256. Measured before being relied on: each document contains exactly one, so
#: a loose pattern is safe here and a precise one would break the day a row is reworded.
DIGEST = re.compile(r"\b[0-9A-F]{64}\b")

#: Size is read per document, anchored on that document's own phrasing, because a general
#: `N bytes` pattern is **not** safe: `tasks.md` carries five such numbers, four of them sizes of
#: things that are not the specification. Each reader must match exactly once — see the guard.
SIZE_READERS = {
    "tasks.md": re.compile(r"`[0-9A-F]{64}`, ([\d,]+) bytes"),
    "AGENTS.md": re.compile(r"\| Size \| ([\d,]+) bytes \|"),
}


def documents() -> dict[str, Path]:
    return {"tasks.md": LEDGER, "AGENTS.md": AGENTS}


def recorded_digests(name: str) -> list[str]:
    return DIGEST.findall(documents()[name].read_text(encoding="utf-8"))


def recorded_sizes(name: str) -> list[int]:
    text = documents()[name].read_text(encoding="utf-8")
    return [int(found.replace(",", "")) for found in SIZE_READERS[name].findall(text)]


def test_the_specification_is_where_both_documents_say_it_is() -> None:
    assert SPECIFICATION.is_file(), f"the specification is missing at {SPECIFICATION}"


# --- the guards on the guards: a reader that finds nothing proves nothing ------------------------


@pytest.mark.parametrize("name", sorted(documents()))
def test_each_document_records_a_digest(name: str) -> None:
    """`T-192` criterion 4. Without this, deleting the row would make every check below pass."""
    assert recorded_digests(name), f"{name} records no SHA-256 for the specification"


@pytest.mark.parametrize("name", sorted(documents()))
def test_each_document_records_exactly_one_size(name: str) -> None:
    """Criterion 4 for the size reader, which is the anchored one and so the fragile one."""
    assert len(recorded_sizes(name)) == 1, (
        f"{name}: the size reader matched {recorded_sizes(name)}, expected exactly one"
    )


# --- the claim itself ----------------------------------------------------------------------------


def test_the_two_documents_record_the_same_digest() -> None:
    """`T-192` criterion 2. Half an update is worse than none: two binding files would then
    disagree about whether the user's source document had changed."""
    everywhere = {digest for name in documents() for digest in recorded_digests(name)}

    assert len(everywhere) == 1, f"the documents record differing digests: {sorted(everywhere)}"


def test_the_two_documents_record_the_same_size() -> None:
    everywhere = {size for name in documents() for size in recorded_sizes(name)}

    assert len(everywhere) == 1, f"the documents record differing sizes: {sorted(everywhere)}"


def test_the_recorded_digest_is_the_specifications_own() -> None:
    """`T-192` criterion 1, and the reason this file exists. Recomputed, never restated."""
    computed = hashlib.sha256(SPECIFICATION.read_bytes()).hexdigest().upper()
    recorded = recorded_digests("tasks.md")[0]

    assert computed == recorded, (
        "the specification does not match the digest this repository records for it. Either it "
        "was modified — which `AGENTS.md` forbids the loop to do — or an edit was authorised and "
        "the recorded hash was not refreshed in both `tasks.md` and `AGENTS.md` (`T-183`)."
    )


def test_the_recorded_size_is_the_specifications_own() -> None:
    assert len(SPECIFICATION.read_bytes()) == recorded_sizes("AGENTS.md")[0]


# --- §22: the superseded specification is not vendored -------------------------------------------


def test_the_superseded_specification_is_not_vendored() -> None:
    """`T-192` criterion 5. §22 supersedes v0.2, and `tasks.md` row 10 records that it is
    "deliberately not vendored" — a claim in the same sentence as the hash, and equally unchecked
    until now. Searched by pattern rather than by exact filename: a copy under any name that says
    NEMOCLAW is the thing this forbids."""
    vendored = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in REPO_ROOT.rglob("*NEMOCLAW*")
        if path.is_file() and ".git" not in path.parts
    )

    assert not vendored, f"the superseded v0.2 specification is vendored: {vendored}"


def test_exactly_one_specification_is_vendored() -> None:
    """The other half of the same claim. Two copies means one of them is not the one being
    hashed, and a reader has no way to tell which they opened."""
    copies = sorted(
        path.relative_to(REPO_ROOT).as_posix()
        for path in REPO_ROOT.rglob("*_SALES_AGENT_SPEC_*.md")
        if path.is_file() and ".git" not in path.parts
    )

    assert copies == ["docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md"], copies
