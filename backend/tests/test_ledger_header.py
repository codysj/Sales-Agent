"""The ledger header says what is true now (T-176; process.md §3, §19.6).

The header table is the one summary `tasks.md` has, and it is the row an audit once caught claiming
"no dashboard code exists" months of work later. Three things are checked, and none of them is
"the file parses":

* **It quotes no test count.** A current-state summary carrying point-in-time numbers is stale the
  moment the next test lands — which is exactly what happened: it said 161, then 182, then "the 182
  tests", while the suite was at 185. Dated numbers belong in completion evidence, which says when
  they were observed.
* **Its `IN_PROGRESS` row agrees with the task blocks.** A header claiming a task nobody is holding,
  or holding one the blocks call `DONE`, is how two invocations come to disagree about ownership.
* **Every task it names exists.** A header pointing at a task ID that was never written is a
  reference a reader cannot follow.
* **Its recommendation agrees with the `READY` set** (T-177). `READY` is the ledger's own word for
  startable, so a header saying "none this loop can start" while two task IDs carry `READY` is the
  summary contradicting the field it summarizes. That one survived because tasks have *two*
  representations — `#### T-###` blocks and §8's gated-epic table — and every census run against
  this ledger had scanned only the first, which is how a `READY` `T-094` stayed invisible.

Scoped to the header rows on purpose. A whole-file scan would flag the task block that *describes*
this defect, which is the same self-reference trap that made an earlier detector read its own
docstring.
"""

import re
from pathlib import Path

import pytest

LEDGER = Path(__file__).resolve().parents[2] / "tasks.md"

#: Header rows are `| **Label** | value |`. These are the ones with claims worth holding.
STAGE_ROW = "Current implementation stage"
IN_PROGRESS_ROW = "`IN_PROGRESS` task"
NEXT_READY_ROW = "Next recommended `READY` task"

#: What a quoted suite size looks like: "182 frontend tests", "the 182 tests", "2314 passed".
TEST_COUNT = re.compile(
    r"\b\d{2,}\s+(?:frontend\s+|dashboard\s+|backend\s+)?tests?\b|\b\d{2,}\s+passed\b"
)


def ledger() -> str:
    return LEDGER.read_text(encoding="utf-8")


def header_row(label: str) -> str:
    """The value cell of the header row carrying ``label``."""
    for line in ledger().splitlines():
        if line.startswith("| ") and label in line:
            return line
    raise AssertionError(f"the header has no {label!r} row")


def known_task_ids() -> set[str]:
    """Every task the ledger defines: `#### T-###` blocks plus §8's gated-epic table rows."""
    text = ledger()
    ids = set(re.findall(r"^#### (T-\d+[a-z0-9]*) ", text, re.MULTILINE))
    ids |= set(re.findall(r"^\| `(T-\d+[a-z0-9]*)` \|", text, re.MULTILINE))
    return ids


#: A task block declares its status in one of **two** formats; `T-060` to `T-071` use the second:
#:
#:   - **Status:** `DONE` (2026-07-31)
#:   - **Stage / Priority:** 2 / P1 — **Status:** `DONE` (2026-07-31) — **Depends on:** T-062
#:
#: Both are anchored to a bullet *label*, which is what keeps prose out: a paragraph that mentions
#: another task being `DONE` never begins with either label.
STATUS_ON_ITS_OWN_LINE = re.compile(r"^- \*\*Status:\*\* `(\w+)`")
STATUS_INLINE = re.compile(r"^- \*\*Stage / Priority:\*\*.*?\*\*Status:\*\* `(\w+)`")


#: A block ends at the next task heading, **the next `## ` section heading**, or end of file
#: (`T-181`). Without the section bound the last `####` in the file runs to EOF: `T-152` was 337
#: lines and held all of §8's table and §9's progress log, against a next-largest block of 36.
#: `^## ` cannot match `### Stage …` — the third `#` is not the space the pattern needs.
#:
#: `\Z` is **currently unreachable and kept deliberately**: every task block today is followed by
#: another `####` or by a `## ` section, so removing it changes nothing and a control mutating it
#: does not bite. It stays because the shape it covers — a task block that ends the file — is one
#: appended task away, and the failure it would cause is the silent kind: the block simply stops
#: being censused. `test_every_task_heading_yields_exactly_one_block` is what would catch that.
TASK_BLOCK = re.compile(r"^#### (T-\d+[a-z0-9]*) .*?(?=^#### |^## |\Z)", re.MULTILINE | re.DOTALL)


def task_blocks() -> list[tuple[str, str]]:
    """Every `#### T-###` block in the ledger, as (task id, block text)."""
    return [(found.group(1), found.group(0)) for found in TASK_BLOCK.finditer(ledger())]


def status_of(block: str) -> str | None:
    """The status a task block declares, in whichever format it uses (`T-179`).

    Scans in line order and returns the first hit. A block's own metadata is its first two lines,
    so it always wins over a status quoted later in the block's prose — the self-reference trap
    that once had a detector reading its own docstring.
    """
    for line in block.splitlines():
        for pattern in (STATUS_ON_ITS_OWN_LINE, STATUS_INLINE):
            if found := pattern.match(line):
                return found.group(1)
    return None


def ready_task_ids() -> set[str]:
    """Every task the ledger marks `READY`, in **both** places tasks are defined (`T-177`).

    Reading only `#### T-###` blocks is the blindness this exists to prevent: §8's gated epics
    are table rows, and a `READY` one there went unnoticed for the whole loop.
    """
    ready = {task_id for task_id, block in task_blocks() if status_of(block) == "READY"}
    ready |= set(re.findall(r"^\| `(T-\d+[a-z0-9]*)` \| `READY` \|", ledger(), re.MULTILINE))
    return ready


def test_the_header_rows_this_file_checks_exist() -> None:
    # The guard on the guard: a renamed label would make every check below vacuous.
    assert header_row(STAGE_ROW)
    assert header_row(IN_PROGRESS_ROW)
    assert header_row(NEXT_READY_ROW)
    assert len(known_task_ids()) > 100, "the task-ID scan found almost nothing; it is misreading"


def test_the_ready_census_reads_both_representations() -> None:
    """`T-177` criterion 3. §8's table defines tasks no `#### T-###` block defines, so a census
    that scans only blocks is blind to them — which is exactly how a `READY` task hid."""
    text = ledger()
    from_blocks = set(re.findall(r"^#### (T-\d+[a-z0-9]*) ", text, re.MULTILINE))
    from_table = set(re.findall(r"^\| `(T-\d+[a-z0-9]*)` \|", text, re.MULTILINE))

    assert from_table - from_blocks, (
        "no task is defined only in §8's table; if the table was converted to task blocks, this "
        "guard and the two-representation scan in ready_task_ids() are obsolete together"
    )


def test_every_task_block_declares_a_status_the_census_can_read() -> None:
    """`T-179` criterion 1.

    A block whose status the census cannot parse is worse than one with no status: it is skipped
    in silence, so it can be `READY` or `IN_PROGRESS` while every check above reports nothing.
    Deliberately phrased as "none unreadable" rather than a block count, per `T-176` — a number
    here would go stale the next time a task is filed.
    """
    unreadable = [task_id for task_id, block in task_blocks() if status_of(block) is None]

    assert not unreadable, (
        f"{unreadable} declare a status the census cannot read; it understands "
        f"`- **Status:** `X`` and the inline `- **Stage / Priority:** … — **Status:** `X`` form"
    )


def test_no_task_block_swallows_the_section_after_it() -> None:
    """`T-181` criterion 1.

    The last `####` in the file has nothing after it to stop at, so an unbounded parser hands the
    final task every section that follows. Nothing reads block *content* today, which is why this
    was latent rather than wrong — and why it is worth closing before something does.
    """
    swallowed = {
        task_id: heading.group(0).strip()
        for task_id, block in task_blocks()
        if (heading := re.search(r"^## .*$", block, re.MULTILINE))
    }

    assert not swallowed, f"these task blocks run past the end of their section: {swallowed}"


def test_every_task_heading_yields_exactly_one_block() -> None:
    """`T-181` criterion 2 — the guard on the boundary fix.

    Tightening where a block *ends* is one edit away from dropping the block that has no
    successor, and the failure would be silent: the task simply stops being censused.
    """
    headings = re.findall(r"^#### (T-\d+[a-z0-9]*) ", ledger(), re.MULTILINE)
    parsed = [task_id for task_id, _ in task_blocks()]

    assert parsed == headings, (
        f"the block scan and the heading scan disagree; missing "
        f"{sorted(set(headings) - set(parsed))}, extra {sorted(set(parsed) - set(headings))}"
    )


def test_both_block_formats_are_read() -> None:
    """`T-179` criterion 1, the positive half — synthetic blocks, so this cannot rot as the real
    ledger changes, and it says plainly which two shapes are supported."""
    own_line = "#### T-001 — A task\n- **Stage / Priority:** 2 / P2\n- **Status:** `READY`\n"
    inline = (
        "#### T-069 — Operations panel\n"
        "- **Stage / Priority:** 2 / P1 — **Status:** `DONE` (2026-07-31) — **Depends on:** T-062\n"
    )

    assert status_of(own_line) == "READY"
    assert status_of(inline) == "DONE"


def test_a_status_quoted_in_prose_is_not_read_as_the_blocks_own() -> None:
    """`T-179` criterion 3. Widening the match is the obvious fix and the dangerous one: task
    blocks routinely discuss other tasks' statuses, and this file's own blocks are full of them."""
    declared = (
        "#### T-999 — A task whose prose discusses other tasks\n"
        "- **Stage / Priority:** 2 / P2\n"
        "- **Status:** `READY`\n"
        "- **Found by:** noticing `T-064` is `DONE` while `T-172` is `BLOCKED`.\n"
    )

    assert status_of(declared) == "READY"

    # The half that actually needs the anchor. A block whose own label is mistyped must read as
    # *unknown* — and so be reported by the test above — rather than quietly inheriting whatever
    # status its prose happens to mention. Line order alone would not catch this one.
    undeclared = (
        "#### T-998 — A task whose status label is mistyped\n"
        "- **Stage / Priority:** 2 / P2\n"
        "- **State:** `READY`\n"
        "- **Found by:** noticing that **Status:** `DONE` appears in this sentence.\n"
    )

    assert status_of(undeclared) is None


#: How a task block records what is stopping it. Anchored to the bullet *label*, for the same
#: reason `STATUS_ON_ITS_OWN_LINE` is: task blocks routinely discuss other tasks' blockers in
#: prose, and a loose match would read one of those as the block's own.
BLOCKER_LINE = re.compile(r"^- \*\*Blocker / Q:\*\*", re.MULTILINE)


def test_every_blocked_task_declares_a_blocker_the_census_can_read() -> None:
    """`T-199`. The `Status` half of this guarantee is `T-179`'s; this is the other half.

    Every idle iteration of the loop enumerates the `BLOCKED` tasks and re-checks that each still
    waits on something real — a blocker that has quietly cleared is work nobody can see is
    available. That audit reads this label. A block that states its blocker in prose instead is
    therefore never re-checked, and reads to the scan as having no blocker at all.

    It is not hypothetical: `T-071c` was written as `**Blocker / Q — the approval question…**`,
    an em-dash continuation rather than the label, and the audit that found it duly reported
    *"(no Blocker / Q line)"* for the single task this repository is waiting on.

    Only `BLOCKED` tasks are required to carry it. A `DONE` or `READY` block naming no blocker is
    saying the true thing.
    """
    missing = [
        task_id
        for task_id, block in task_blocks()
        if status_of(block) == "BLOCKED" and not BLOCKER_LINE.search(block)
    ]

    assert not missing, (
        f"{missing} are BLOCKED but declare no `- **Blocker / Q:**` line; the blocker census "
        f"cannot see them, so nobody will ever re-check whether they are still blocked"
    )


def test_the_blocker_scan_is_not_vacuous() -> None:
    """The guard on the guard. If nothing is `BLOCKED`, or the label were renamed, the check
    above passes while proving nothing — which is the failure mode it exists to prevent."""
    blocked = [task_id for task_id, block in task_blocks() if status_of(block) == "BLOCKED"]
    found = [
        task_id
        for task_id, block in task_blocks()
        if status_of(block) == "BLOCKED" and BLOCKER_LINE.search(block)
    ]

    assert blocked, "no task is BLOCKED; the check above is vacuous and should be reconsidered"
    assert found == blocked


def test_a_blocker_named_in_prose_is_not_read_as_the_blocks_own() -> None:
    """The anchor earns its keep here exactly as it does for `Status`: this ledger's blocked
    tasks quote each other's blockers constantly."""
    labelled = (
        "#### T-999 — A blocked task\n"
        "- **Stage / Priority:** 2 / P2\n"
        "- **Status:** `BLOCKED`\n"
        "- **Blocker / Q:** `Q-004` has chosen no mailbox.\n"
    )
    prose_only = (
        "#### T-998 — A blocked task whose blocker is a sentence\n"
        "- **Stage / Priority:** 2 / P2\n"
        "- **Status:** `BLOCKED`\n"
        "- **Blocker / Q — the approval question.** Discussed at length below.\n"
    )

    assert BLOCKER_LINE.search(labelled)
    assert not BLOCKER_LINE.search(prose_only)


def test_the_stage_description_quotes_no_test_count() -> None:
    """`T-176` criterion 1. The drift class, not the instance: numbers here go stale silently."""
    found = TEST_COUNT.findall(header_row(STAGE_ROW))

    assert not found, (
        f"the stage description quotes suite sizes {found}; they belong in completion evidence, "
        f"which dates them"
    )


def test_the_stage_description_names_what_actually_blocks_the_gate() -> None:
    """It once said the remaining work was `T-070b` and `T-071`, after `T-172` had become the
    binding blocker. A summary that omits the blocker sends a reader at the wrong thing."""
    row = header_row(STAGE_ROW)

    assert "T-172" in row, "the stage description does not name T-172, which blocks gate G-10"


def test_the_in_progress_row_agrees_with_the_task_blocks() -> None:
    """`T-176` criterion 2. At most one task may hold it (§1), and the header is where a fresh
    invocation looks first."""
    row = header_row(IN_PROGRESS_ROW)
    claimed = re.findall(r"`(T-\d+[a-z0-9]*)`", row)

    if not claimed:
        assert "*none*" in row, f"the IN_PROGRESS row names no task and does not say *none*: {row}"
        return

    assert len(claimed) == 1, f"the header claims more than one IN_PROGRESS task: {claimed}"
    blocks = dict(task_blocks())
    assert claimed[0] in blocks, f"the header claims {claimed[0]}, which has no task block"
    # Read through `status_of`, not a substring search: `"**Status:** `IN_PROGRESS`" in block`
    # would also match the phrase appearing anywhere in the block's prose.
    assert status_of(blocks[claimed[0]]) == "IN_PROGRESS", (
        f"the header claims {claimed[0]} is IN_PROGRESS; its block says "
        f"{status_of(blocks[claimed[0]])}"
    )


def test_the_next_recommended_row_names_every_ready_task() -> None:
    """`T-177` criterion 1. The row is the reader's shortcut past a status census; if it omits a
    `READY` task, the shortcut is worse than no shortcut."""
    named = set(re.findall(r"`(T-\d+[a-z0-9]*)`", header_row(NEXT_READY_ROW)))
    missing = ready_task_ids() - named

    assert not missing, (
        f"the ledger marks {sorted(missing)} `READY` and the next-recommended row does not name "
        f"them; say why each is or is not worth starting"
    )


def test_the_row_says_none_only_when_nothing_is_ready() -> None:
    """`T-177` criterion 2. It said "none this loop can start" while two tasks carried `READY`."""
    row = header_row(NEXT_READY_ROW)
    ready = ready_task_ids()

    if re.search(r"\bnone\b", row, re.IGNORECASE):
        assert not ready, (
            f"the next-recommended row says *none* while {sorted(ready)} are marked `READY`; "
            f"`READY` is the ledger's own word for startable"
        )


@pytest.mark.parametrize("label", [STAGE_ROW, IN_PROGRESS_ROW, NEXT_READY_ROW])
def test_every_task_the_header_names_exists(label: str) -> None:
    """`T-176` criterion 3, extended to the recommendation row by `T-177`."""
    named = set(re.findall(r"`(T-\d+[a-z0-9]*)`", header_row(label)))
    missing = named - known_task_ids()

    assert not missing, f"the {label!r} row names tasks that do not exist: {sorted(missing)}"
