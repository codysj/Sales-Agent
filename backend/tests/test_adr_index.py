"""Every local decision record is findable, and a proposal stays a proposal (T-174; §16, §0.1).

`docs/adr/README.md` is the index a reader reaches for, and an ADR that is written but not listed
is a decision nobody will find — which is the same outcome as not having written it. So the check
is not that the directory has files; it is that the index and the directory agree.

Two further things are checked, and both came from the index being wrong rather than from
foresight.

**A proposal may not be promoted without a decision.** `AWAITING_A_DECISION` names any ADR the loop
wrote but may not accept for itself; promoting one would silently turn a question into an answer
the loop gave. It is empty today — ADR-027 was accepted by the user on 2026-08-01 — and the
mechanism stays for the next proposal.

**The index's status column must agree with the record's own** (`T-186`). It did not: the index
called ADR-027 `PROPOSED` and *"awaiting the user"* a full day after they accepted it and `T-172a`
had implemented it. Every check here already compared the index and the directory about which ADRs
*exist*; none compared what they *say*, and the index is what a reader reaches for first.

Offline: this reads two directories of text.
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[2] / "docs" / "adr"
INDEX = DOCS / "README.md"

#: The specification's status vocabulary (§0.1). A status outside it is a typo, not a state.
STATUSES = frozenset({"ACCEPTED", "PROPOSED", "DEFERRED", "REJECTED", "SUPERSEDED"})

#: ADRs that must not be `ACCEPTED` without somebody deciding, and why. A proposal the loop
#: promoted itself would read exactly like a decision the user made.
#: Empty since 2026-08-01: the user accepted **ADR-027** (option (b)), so the one entry this
#: held has been removed. The mechanism stays for the next proposal the loop writes — it
#: is the thing that makes "the loop may not decide this" enforceable rather than a habit.
AWAITING_A_DECISION: dict[str, str] = {}


def local_adrs() -> list[Path]:
    """Every `ADR-0NN-*.md` in the directory. ADR-001…017 are inherited and live in the spec."""
    return sorted(path for path in DOCS.glob("ADR-*.md"))


def adr_number(path: Path) -> str:
    return path.name.split("-")[0] + "-" + path.name.split("-")[1]


def status_of(path: Path) -> str:
    """The `**Status:** X` on the first line that declares one."""
    match = re.search(r"\*\*Status:\*\*\s+([A-Z]+)", path.read_text(encoding="utf-8"))
    assert match is not None, f"{path.name} declares no status"
    return match.group(1)


@pytest.fixture
def adr_027() -> Path:
    matching = [path for path in local_adrs() if adr_number(path) == "ADR-027"]
    assert matching, "ADR-027 is missing"
    return matching[0]


def test_there_are_local_adrs_to_check() -> None:
    # The guard on the guard: an empty glob would make every test below vacuously true.
    assert len(local_adrs()) >= 10, "the ADR directory looks wrong; the checks below prove nothing"


@pytest.mark.parametrize("path", local_adrs(), ids=lambda path: path.stem[:11])
def test_every_local_adr_is_in_the_index(path: Path) -> None:
    """An unindexed ADR is a decision nobody finds, which is the same as no decision."""
    index = INDEX.read_text(encoding="utf-8")

    assert path.name in index, f"{path.name} is not linked from docs/adr/README.md"


@pytest.mark.parametrize("path", local_adrs(), ids=lambda path: path.stem[:11])
def test_every_local_adr_declares_a_known_status(path: Path) -> None:
    assert status_of(path) in STATUSES, f"{path.name}: unknown status {status_of(path)!r}"


@pytest.mark.parametrize(
    ("number", "reason"), sorted(AWAITING_A_DECISION.items()), ids=lambda value: str(value)[:11]
)
def test_a_proposal_is_not_promoted_without_a_decision(number: str, reason: str) -> None:
    """`T-174` criterion 3. The loop wrote ADR-027; only the user may accept it."""
    matching = [path for path in local_adrs() if adr_number(path) == number]
    assert matching, f"{number} is listed as awaiting a decision but no such ADR exists"

    assert status_of(matching[0]) == "PROPOSED", (
        f"{number} is {status_of(matching[0])}, not PROPOSED: {reason}"
    )


def test_the_proposal_records_that_it_was_corrected(adr_027: Path) -> None:
    """`T-175`. The first version of ADR-027 claimed option (b) amends no invariant; it does — the
    adapter walks catch `app/cli.py`, the caller their own docstrings name.

    Asserted because a control proved nothing held it: reverting the correction failed no test, so
    the accuracy of a document somebody is asked to *decide on* rested on nobody editing it. The
    check is the claim, not the wording: (b) must not be sold as free.
    """
    text = adr_027.read_text(encoding="utf-8")

    assert "Corrected 2026-08-01" in text, "the correction is no longer visible as a correction"
    assert "amends no invariant" not in text.replace("amends no invariant.**", ""), (
        "ADR-027 claims option (b) amends no invariant again"
    )
    assert "cli.py" in text, "the ADR no longer names the module the invariants catch"


#: An index row for a **local** ADR: the file it links and its status cell. Anchored on the link
#: so the inherited ADR-001…017 rows, which name no file and carry the specification's own
#: `DECIDED`, are not swept in — there is no record here for those to disagree with.
INDEX_ROW = re.compile(r"^\| \[ADR-\d+\]\((ADR-\d+-[^)]+\.md)\) \| ([^|]*) \|", re.MULTILINE)

#: The status word inside a cell that may carry more: ADR-021 reads `ACCEPTED (amended)` and
#: ADR-027 was once `**PROPOSED**`. Both sides are read the same way — `status_of` takes the first
#: all-caps run after `**Status:**` — so a qualifier is allowed and a *different word* is not.
STATUS_WORD = re.compile(r"[A-Z]{4,}")


def indexed_statuses() -> dict[str, str]:
    """Linked filename -> the status the index claims for it."""
    found: dict[str, str] = {}
    for filename, cell in INDEX_ROW.findall(INDEX.read_text(encoding="utf-8")):
        word = STATUS_WORD.search(cell)
        assert word is not None, f"the index row for {filename} declares no status: {cell!r}"
        found[filename] = word.group(0)
    return found


def test_the_index_has_a_well_formed_row_for_every_local_adr() -> None:
    """The guard on the check below: a row this parser cannot read is a row it cannot compare.

    `test_every_local_adr_is_in_the_index` only asks whether the filename appears *somewhere*, so
    a malformed row would satisfy it and silently drop out of the status comparison.
    """
    assert set(indexed_statuses()) == {path.name for path in local_adrs()}


@pytest.mark.parametrize("path", local_adrs(), ids=lambda path: path.stem[:11])
def test_the_index_agrees_with_the_record_about_its_status(path: Path) -> None:
    """`T-186`. The index said ADR-027 was `PROPOSED` and awaiting the user for a day after they
    had accepted it — the record itself was right, and the page a reader opens first was not."""
    claimed = indexed_statuses()[path.name]

    assert claimed == status_of(path), (
        f"docs/adr/README.md calls {path.name} {claimed}; the record says {status_of(path)}"
    )


def test_the_index_lists_nothing_that_does_not_exist() -> None:
    """The other direction: a row pointing at a deleted file is a broken link in the one place a
    reader trusts."""
    index = INDEX.read_text(encoding="utf-8")
    linked = set(re.findall(r"\((ADR-\d+-[^)]+\.md)\)", index))
    present = {path.name for path in local_adrs()}

    assert not (linked - present), (
        f"the index links files that do not exist: {sorted(linked - present)}"
    )
