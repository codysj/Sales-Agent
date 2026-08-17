"""No real address reaches the public remote (T-182; `AGENTS.md` rule 1, §15.5).

`AGENTS.md` rule 1 is one sentence with two halves: fixtures use "a visible `SYNTHETIC-` prefix
**and IANA reserved example domains**", because this repository has a public GitHub remote.
`tests/test_fixtures.py` holds the prefix half thoroughly — names, prose, and no digits, so no
roadmap date or price can appear. This file holds the domain half, which nothing enforced.

It was not enforced and it had already decayed: `tests/test_prospects.py` opened with "All fixtures
use IANA reserved example domains. No real company, person, or address appears." while carrying two
single-letter normalization inputs at registrable `.com` names, and a neighbouring test had been
corrected to `A@X.example.com` with its docstring left quoting the old value. None of that was a
prospect record and none of it did any harm — which is the point. The rule exists so nobody has to
judge whether a given address is real enough, and the case worth catching is a genuine prospect
address pasted into a fixture, caught when it lands.

**Those inputs are described here rather than quoted, and so is the task block that records this
work.** The check has no exemption list on purpose: a file allowed to hold "explanatory" addresses
is precisely where a real one would survive. Prose that needs to name a bad address should describe
its shape.

Scoped to **email addresses**. A bare domain in prose is often legitimate — `linkedin.com` is named
by ADR-005, which rejects automating it — and widening this to every hostname would flag those.
"""

import re
import subprocess
from functools import cache
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Directories that are not the repository: build output, caches, and vendored dependencies. The
#: walk prunes these rather than reading them, which also keeps it fast.
NOT_THE_REPOSITORY = frozenset(
    {
        ".git",
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".next",
        ".turbo",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "coverage",
    }
)

NOT_TEXT = frozenset({".png", ".ico", ".jpg", ".jpeg", ".gif", ".pdf", ".woff", ".woff2", ".db"})

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

#: RFC 2606 and RFC 6761 reserved names: these can never belong to anyone.
RESERVED_SUFFIXES = (".invalid", ".test", ".example", ".localhost")
RESERVED_DOMAINS = frozenset({"example.com", "example.org", "example.net"})


def is_reserved(domain: str) -> bool:
    """True if ``domain`` is one nobody can register, at any depth of subdomain."""
    cleaned = domain.lower().rstrip(".")
    if cleaned.endswith(RESERVED_SUFFIXES):
        return True
    labels = cleaned.split(".")
    return len(labels) >= 2 and ".".join(labels[-2:]) in RESERVED_DOMAINS


@cache
def repository_files() -> tuple[Path, ...]:
    """Every file that could reach the remote: tracked, plus untracked and not ignored.

    **Asked of git rather than of the filesystem (`T-218`).** This check's subject is the sentence
    at the top of the file — *no real address reaches the public remote* — and the filesystem walk
    it used to do answered a wider question: every file on this machine. Those differ by exactly
    the ignored files, and `.gitignore` exists to hold the things that must not be published.
    `Q-004`'s answer put the outreach mailbox in an untracked `.env` **on the user's instruction
    that it stay out of git**, and the walk then failed the suite for it — a check reporting a
    violation of a rule that was being followed.

    `--cached --others --exclude-standard` is tracked plus untracked-but-not-ignored, which is
    what somebody could commit next. An ignored file cannot be added without `-f`, and a file
    unignored later shows up here the moment it is.

    Deliberately **not** an exemption list. The docstring above warns against one, and it is right:
    a file permitted to hold "explanatory" addresses is where a real one would survive. This
    narrows *what the repository is*, and every file in it is still checked with no exceptions.
    """
    listed = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=REPO,
        capture_output=True,
        check=True,
    )
    found: list[Path] = []
    for name in listed.stdout.decode("utf-8").split("\0"):
        if not name:
            continue
        path = REPO / name
        if any(part in NOT_THE_REPOSITORY for part in path.parts):
            continue
        if path.is_file() and path.suffix.lower() not in NOT_TEXT:
            found.append(path)
    return tuple(found)


@cache
def addresses() -> dict[str, set[str]]:
    """Every email address in the repository, mapped to the files it appears in."""
    found: dict[str, set[str]] = {}
    for path in repository_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:  # pragma: no cover - unreadable file, nothing to assert about it
            continue
        for address in EMAIL.findall(text):
            found.setdefault(address, set()).add(str(path.relative_to(REPO)))
    return found


def test_every_email_address_uses_a_reserved_domain() -> None:
    """`T-182` criterion 1."""
    offenders = {
        address: sorted(files)
        for address, files in addresses().items()
        if not is_reserved(address.rsplit("@", 1)[1])
    }

    assert not offenders, (
        f"these addresses use domains somebody owns: {offenders}. AGENTS.md rule 1 requires IANA "
        f"reserved domains — *.invalid, *.test, *.example, *.localhost, or example.com/.org/.net"
    )


def test_the_address_scan_is_not_vacuous() -> None:
    """`T-182` criterion 2 — the guard on the guard.

    Three ways the check above quietly stops meaning anything: the listing stops finding files (a
    pruned directory name that matches too much, or a `git ls-files` that answered with nothing),
    the pattern stops matching addresses, or — since `T-218` — the listing silently loses the
    untracked half and stops seeing a file before anybody commits it. The repository is full of
    legitimate reserved addresses, so all three are observable.
    """
    files = repository_files()
    reserved = [address for address in addresses() if is_reserved(address.rsplit("@", 1)[1])]

    assert len(files) > 100, f"the listing found only {len(files)} files; it is pruning too much"
    assert reserved, "the scan found no email address at all; the pattern is matching nothing"

    # The untracked half, demonstrated rather than assumed. A file written and not yet committed
    # is the shape a pasted prospect address actually arrives in, and `--cached` alone would miss
    # every one of them until they were pushed. Asserting on whatever the working tree happens to
    # contain would pass or fail depending on when somebody last committed, so this makes the
    # condition it needs: a new file, listed, then removed.
    probe = REPO / "test_synthetic_data_untracked_probe.txt"
    probe.write_text("reserved@example.invalid\n", encoding="utf-8")
    try:
        fresh = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=REPO,
            capture_output=True,
            check=True,
        )
        listed_now = {name for name in fresh.stdout.decode("utf-8").split("\0") if name}
    finally:
        probe.unlink()

    assert probe.name in listed_now, (
        "a new, uncommitted file was not listed; the scan is seeing only committed files, and an "
        "address pasted into a new one would go unseen until it was pushed"
    )
