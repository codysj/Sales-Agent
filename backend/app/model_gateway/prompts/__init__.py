"""Versioned prompts (T-053; specification §10.2, §14.5, §17.5, §19.3).

Prompts are files, hashed and registered as `PromptVersion` rows, for the same reason schemas
are (`T-051`): a `ModelRun` cites the prompt version it ran under, and a prompt edited in place
would make an old decision unexplainable. Registration follows the same rules — idempotent when
unchanged, next version when changed, previous window closed.

The template lives in a `.txt` file rather than a Python string so a reviewer can read the exact
words the model is given without reading around escaping, and so a diff of a prompt change is a
diff of prose.
"""

from datetime import datetime
from pathlib import Path
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import PromptVersion, content_hash

PROMPT_DIR: Final = Path(__file__).resolve().parent

#: The bounded task each prompt serves (§10.2). Key -> task name.
PROMPT_TASKS: Final[dict[str, str]] = {
    "qualification": "qualification",
    "draft": "draft",
}

__all__ = [
    "PROMPT_DIR",
    "PROMPT_TASKS",
    "prompt_template",
    "register_prompt_versions",
    "registered_prompt",
]


def prompt_template(key: str) -> str:
    """The template text for ``key``."""
    if key not in PROMPT_TASKS:
        raise KeyError(f"no prompt registered under {key!r}")
    return (PROMPT_DIR / f"{key}.txt").read_text(encoding="utf-8")


def registered_prompt(session: Session, key: str) -> PromptVersion | None:
    """The highest registered version of ``key``, or ``None``."""
    return (
        session.execute(
            select(PromptVersion)
            .where(PromptVersion.key == key)
            .order_by(PromptVersion.version.desc())
        )
        .scalars()
        .first()
    )


def register_prompt_versions(
    session: Session, *, created_by: str, at: datetime
) -> list[PromptVersion]:
    """Register any prompt whose text differs from its latest registered version."""
    published: list[PromptVersion] = []

    for key in sorted(PROMPT_TASKS):
        template = prompt_template(key)
        digest = content_hash(template)

        latest = registered_prompt(session, key)
        if latest is not None and latest.content_hash == digest:
            continue

        version = PromptVersion(
            key=key,
            version=(latest.version + 1) if latest else 1,
            content_hash=digest,
            effective_from=at,
            created_by=created_by,
            task_name=PROMPT_TASKS[key],
            template=template,
        )
        if latest is not None:
            latest.effective_to = at
        session.add(version)
        published.append(version)

    session.flush()
    return published
