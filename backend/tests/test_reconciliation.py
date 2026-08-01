"""Reconciliation records do not outlive their revisit triggers (T-180; process.md §8).

`docs/reconciliation.md` parks a spec-vs-implementation divergence with an interpretation and,
sometimes, a condition for reopening it: *"revisit at `T-069`"*. That is only safe while somebody
notices `T-069` landing. Two records — `R-003` and `R-005` — sat `OPEN` with triggers that had
already closed, and nothing said so; the drift was found by reading, months after the fact.

One check, and it is the one that would have caught it: **no `OPEN` record may name a revisit
trigger that is already `DONE`.** The task statuses come from `test_ledger_header`'s parser rather
than a second copy, because `T-179` had just finished teaching that parser to read both of the
ledger's block formats and a duplicate would drift from it.
"""

import re
from pathlib import Path

from tests.test_ledger_header import status_of, task_blocks

RECONCILIATION = Path(__file__).resolve().parents[2] / "docs" / "reconciliation.md"

#: Rows look like `| **R-003** | ... | OPEN — benign, interpretation recorded |`.
RECORD_ROW = re.compile(r"^\| \*\*(R-\d+)\*\*")
REVISIT_TRIGGER = re.compile(r"revisit at `(T-\d+[a-z0-9]*)`")


def record_rows() -> list[tuple[str, str]]:
    """Every reconciliation row, as (record id, whole line)."""
    return [
        (found.group(1), line)
        for line in RECONCILIATION.read_text(encoding="utf-8").splitlines()
        if (found := RECORD_ROW.match(line))
    ]


def is_open(line: str) -> bool:
    """A row is open unless its state cell says CLOSED. Read from the end: the divergence text
    of `R-001` contains the word "open", so a whole-line search would call a closed row open."""
    return "CLOSED" not in line.rsplit("|", 2)[-2]


def test_no_open_record_waits_on_a_revisit_that_has_already_happened() -> None:
    """`T-180` criterion 2, and the reason this file exists."""
    statuses = {task_id: status_of(block) for task_id, block in task_blocks()}
    stale = {
        record: [
            task
            for task in REVISIT_TRIGGER.findall(line)
            if statuses.get(task) in {"DONE", "SPLIT"}
        ]
        for record, line in record_rows()
        if is_open(line)
    }
    overdue = {record: tasks for record, tasks in stale.items() if tasks}

    assert not overdue, (
        f"{overdue} are OPEN and wait on a revisit whose trigger has already closed; do the "
        f"revisit and record what it found, or name a trigger that has not passed"
    )


def test_the_revisit_scan_is_not_vacuous() -> None:
    """The guard on the guard.

    Two ways the check above quietly stops meaning anything: the row pattern stops matching, or
    the phrase "revisit at" disappears from the document. Closed records keep their trigger text,
    which is what keeps this anchored after every open one has been resolved.
    """
    rows = record_rows()
    document = RECONCILIATION.read_text(encoding="utf-8")

    assert len(rows) >= 2, "the reconciliation row pattern matched almost nothing; it is misreading"
    assert any(is_open(line) for _, line in rows), "no OPEN record; the check above scans nothing"
    assert REVISIT_TRIGGER.search(document), (
        "no 'revisit at `T-###`' anywhere in the document; the trigger pattern is unproven"
    )
