"""Versioned output schemas (T-051; specification §10.4, §14.5, §23, GP-09).

Every bounded model task has a schema, the schema is a file on disk, and the file is registered
as a `SchemaVersion` with a content hash. Three consequences follow, and each is enforced by a
test rather than a convention:

* **A schema change is a new version.** `register_schema_versions` refuses to rewrite a
  registered version whose content has changed; it publishes the next version instead. A run
  cites the version it validated against, so silently editing one would make an old decision
  unexplainable (§17.5).
* **The file and the model cannot drift.** The `.json` artefact is generated from the Pydantic
  model, and `test_output_schemas.py` fails if it is stale. The file exists because §23 wants an
  inspectable, hashable contract; the model exists because it is what actually validates.
* **The registry is the list of what may be validated.** A task naming a schema key that is not
  here has no contract, and the validator refuses rather than guessing one.
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import SchemaVersion, content_hash
from app.model_gateway.schemas.draft import SCHEMA_KEY as DRAFT_KEY
from app.model_gateway.schemas.draft import DraftOutput
from app.model_gateway.schemas.qualification import SCHEMA_KEY as QUALIFICATION_KEY
from app.model_gateway.schemas.qualification import QualificationOutput

SCHEMA_DIR: Final = Path(__file__).resolve().parent

#: Schema key -> the model that defines it. The only schemas that exist.
OUTPUT_SCHEMAS: Final[dict[str, type[BaseModel]]] = {
    QUALIFICATION_KEY: QualificationOutput,
    DRAFT_KEY: DraftOutput,
}

__all__ = [
    "DRAFT_KEY",
    "OUTPUT_SCHEMAS",
    "QUALIFICATION_KEY",
    "SCHEMA_DIR",
    "DraftOutput",
    "QualificationOutput",
    "SchemaTampered",
    "register_schema_versions",
    "schema_document",
    "schema_path",
    "verify_registered_schema",
]


def schema_document(key: str) -> dict[str, Any]:
    """The JSON Schema for ``key``, as Pydantic emits it."""
    model = OUTPUT_SCHEMAS.get(key)
    if model is None:
        raise KeyError(f"no output schema registered under {key!r}")
    return model.model_json_schema()


def schema_path(key: str) -> Path:
    """Where the exported artefact for ``key`` lives."""
    return SCHEMA_DIR / f"{key}.json"


def write_schema_file(key: str) -> Path:
    """Export the artefact. Called by the test that keeps the file honest, not at runtime."""
    path = schema_path(key)
    path.write_text(
        json.dumps(schema_document(key), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def registered_version(session: Session, key: str) -> SchemaVersion | None:
    """The highest registered version of ``key``, or ``None``."""
    return (
        session.execute(
            select(SchemaVersion)
            .where(SchemaVersion.key == key)
            .order_by(SchemaVersion.version.desc())
        )
        .scalars()
        .first()
    )


class SchemaTampered(Exception):
    """A registered schema's body no longer matches the hash it was registered with."""


def verify_registered_schema(session: Session, key: str) -> SchemaVersion:
    """The latest registered version of ``key``, checked against its own content hash.

    `T-023`'s trigger pins `key`, `version`, `content_hash`, `effective_from`, and `created_by`,
    but deliberately leaves `json_schema` and `effective_to` writable — a window has to be
    closable when the next version publishes. That leaves exactly one way to tamper with a
    registered schema: edit the body and leave the hash behind. This is the check that catches
    it, and it is cheap enough to run wherever a schema is about to be trusted.
    """
    version = registered_version(session, key)
    if version is None:
        raise SchemaTampered(f"no registered schema version for {key!r}")
    if version.content_hash != content_hash(version.json_schema):
        raise SchemaTampered(
            f"{key} v{version.version} was edited after registration: its body does not match "
            f"the content hash it was registered with (§17.5, GP-09)"
        )
    return version


def register_schema_versions(
    session: Session,
    *,
    created_by: str,
    at: datetime,
) -> list[SchemaVersion]:
    """Register any schema whose content differs from its latest registered version.

    Idempotent: a schema whose content already matches its latest version registers nothing. A
    *changed* schema publishes the next version rather than editing the current one, which is
    what makes "a run cites the schema it used" true over time (§14.5).
    """
    published: list[SchemaVersion] = []

    for key in sorted(OUTPUT_SCHEMAS):
        document = schema_document(key)
        digest = content_hash(document)

        latest = registered_version(session, key)
        if latest is not None and latest.content_hash == digest:
            continue

        version = SchemaVersion(
            key=key,
            version=(latest.version + 1) if latest else 1,
            content_hash=digest,
            effective_from=at,
            created_by=created_by,
            json_schema=document,
        )
        if latest is not None:
            latest.effective_to = at
        session.add(version)
        published.append(version)

    session.flush()
    return published
