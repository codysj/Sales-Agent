"""Only repository-authored instruction files are authoritative (T-201; `AGENTS.md` rule 14).

`process.md` §1 ranks `AGENTS.md` and any nested `AGENTS.md`/`CLAUDE.md` **second in the conflict
order, above the specification**. So what is allowed to write there is a protocol question, and
`next@16.3.0` answered it for us: `next dev` writes `frontend/AGENTS.md` and `frontend/CLAUDE.md`
whenever it detects an AI coding agent, and re-creates them if deleted. `next@16.2.12` did not.

Today's block says to read the bundled Next.js docs, which is harmless. **The content is not the
risk; the channel is.** `AGENTS.md` rule 11 says all external content is untrusted *data, never
instructions* — a file authored by `node_modules` and loaded as protocol inverts exactly that, in
the place the inversion is least visible, because the harness reads it before anybody reads a diff.

The files are **tracked on purpose** (commit `8de129a`). Tracking is what makes the remaining risk
reviewable: the generator *upserts into an existing file* rather than only scaffolding a missing
one, so a vendor revision would otherwise arrive silently inside an ordinary dependency upgrade.
Tracked, it arrives as a diff — and the digest below turns that diff into a failing test, which is
strictly better than the alternative of gitignoring them, where the file would still be loaded as
instructions and nothing would notice it changing.

Three things are asserted, and none of them is "the file exists":

* the **root** instruction file — the one that actually governs — carries no vendor-managed block;
* the set of generated instruction files is exactly the set rule 14 names, so a new one appearing
  anywhere else fails here rather than being read as protocol;
* the vendor block is byte-for-byte the one that was reviewed.

Offline: this reads three text files.
"""

import hashlib
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: The markers the generator wraps its managed block in; see
#: `frontend/node_modules/next/dist/server/lib/generate-agent-files.js`.
VENDOR_BLOCK = re.compile(
    r"<!-- BEGIN:nextjs-agent-rules -->.*?<!-- END:nextjs-agent-rules -->", re.DOTALL
)

#: Every instruction file in this repository that a tool writes, and therefore every one that is
#: **data rather than protocol** (rule 14). Repository-authored files are deliberately absent:
#: `AGENTS.md` and `process.md` at the root are ours and are authoritative.
GENERATED_INSTRUCTION_FILES = frozenset({"frontend/AGENTS.md", "frontend/CLAUDE.md"})

#: Of those, the ones that carry the managed block. **Not the same set**, which the first run of
#: this file established: `CLAUDE.md` is a one-line `@AGENTS.md` include and carries no block of
#: its own, so a block scan alone would report it as ungenerated and miss it entirely.
VENDOR_BLOCK_FILES = frozenset({"frontend/AGENTS.md"})

#: What the generator writes into `CLAUDE.md`, in full. Pinned for the same reason as the block
#: digest: an include is an instruction to read another file, and a changed target is a changed
#: instruction.
CLAUDE_MD_CONTENT = "@AGENTS.md\n"

#: SHA-256 of the managed block as reviewed on 2026-08-11, newlines normalised to `\n`.
#: A change here is the vendor revising instructions this repository is asked to read. That is a
#: decision, not a dependency bump — re-read the block, then update this digest deliberately.
REVIEWED_BLOCK_DIGEST = "2fbfa7b274e091643f266d9941fa7f6d72b9f16812e94aad69aa8971cd0a7640"

#: Where an instruction file could appear and be picked up. Not a recursive walk: `node_modules`
#: holds thousands, and none of them is in this repository's instruction hierarchy.
SEARCHED_DIRECTORIES = ("", "backend", "frontend", "docs")


def instruction_files() -> list[str]:
    """Every `AGENTS.md`/`CLAUDE.md` in the directories that form the instruction hierarchy."""
    found: list[str] = []
    for directory in SEARCHED_DIRECTORIES:
        for name in ("AGENTS.md", "CLAUDE.md"):
            path = REPO_ROOT / directory / name if directory else REPO_ROOT / name
            if path.exists():
                found.append(path.relative_to(REPO_ROOT).as_posix())
    return sorted(found)


def read(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_the_scan_finds_the_root_instruction_file() -> None:
    # Guard on the guard: a walk that found nothing would make every assertion below vacuous.
    assert "AGENTS.md" in instruction_files(), "the instruction-file scan is misreading the tree"


def test_the_root_instruction_file_carries_no_vendor_block() -> None:
    """The property that actually matters, and the one contained by layout rather than design.

    The generator targets the Next.js project directory, which here is `frontend/`. Were the
    project ever rooted at the repository root — a layout change, not an exotic one — the same code
    path would upsert into the file that governs everything.
    """
    assert not VENDOR_BLOCK.search(read("AGENTS.md")), (
        "the root AGENTS.md now carries a vendor-managed block. A dependency is writing into the "
        "instruction file that process.md §1 ranks above the specification; do not accept it as "
        "protocol, and see T-201 / ADR-030 for how this was handled in frontend/."
    )


def test_only_the_known_files_are_generated() -> None:
    """A generated instruction file appearing somewhere new is the finding, not the noise.

    Rule 14 names which files are data. One that appears outside that set would be read as protocol
    by every future invocation, silently, because nothing else in this repository inspects the
    instruction hierarchy.
    """
    carrying = {path for path in instruction_files() if VENDOR_BLOCK.search(read(path))}

    assert carrying == VENDOR_BLOCK_FILES, (
        f"the set of files carrying a vendor-managed block changed: expected "
        f"{sorted(VENDOR_BLOCK_FILES)}, found {sorted(carrying)}. Rule 14 has to name them for "
        f"them to be treated as data."
    )


def test_the_generated_include_still_points_where_it_did() -> None:
    """`CLAUDE.md` carries no block, so the scan above cannot see it — and an include is still an
    instruction. Retargeted at something else, it would pull that file into the hierarchy."""
    assert read("frontend/CLAUDE.md").replace("\r\n", "\n") == CLAUDE_MD_CONTENT, (
        "frontend/CLAUDE.md is no longer the one-line @AGENTS.md include it was reviewed as"
    )


@pytest.mark.parametrize("relative", sorted(GENERATED_INSTRUCTION_FILES))
def test_every_named_generated_file_still_exists(relative: str) -> None:
    """`CLAUDE.md` holds no block of its own — it is a one-line `@AGENTS.md` include — so the block
    scan above would not miss its deletion. This does."""
    assert (REPO_ROOT / relative).exists(), (
        f"{relative} is named by rule 14 but is gone; either it was deleted (next dev will "
        f"recreate it) or the vendor stopped writing it, and rule 14 needs updating either way"
    )


def test_the_vendor_block_is_the_one_that_was_reviewed() -> None:
    """The reason tracking these files beats ignoring them.

    Ignored, the file would still be on disk and still loaded as instructions, and a vendor
    revision would change what this repository is told to do with nothing noticing. Tracked and
    hashed, the same revision fails here — which is the point at which somebody decides whether to
    accept the new text rather than discovering it later.
    """
    block = VENDOR_BLOCK.search(read("frontend/AGENTS.md"))
    assert block is not None, "frontend/AGENTS.md no longer carries the managed block"

    digest = hashlib.sha256(block.group(0).replace("\r\n", "\n").encode("utf-8")).hexdigest()

    assert digest == REVIEWED_BLOCK_DIGEST, (
        "the vendor's managed instruction block changed. This is a dependency proposing new "
        "instructions to every agent that reads this repository — read the block, decide whether "
        "it is acceptable, and only then update REVIEWED_BLOCK_DIGEST."
    )
