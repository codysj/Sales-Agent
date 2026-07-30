"""Versioned artefacts behind every decision (specification §14.1, §17.5, GP-09).

§17.5 requires every recorded action to carry "application, prompt, schema, model, policy, and
runtime versions". These four tables are what those references point at, so a decision made six
weeks ago can still be explained by reading exactly what produced it.

Two properties make that work:

* **Immutable once written.** Editing a prompt or a schema in place would silently rewrite the
  basis of every model run that cites it — the run would claim a version whose content had since
  changed. Editing means publishing the next version.
* **One effective version per key per instant**, enforced by a PostgreSQL exclusion constraint
  rather than an application check, exactly as product readiness is (`T-013`). Two "current"
  prompts would make a model run unattributable.

**`PolicyVersion` here is the *global* policy record** — messaging guidance, objection handling,
and anything else not scoped to one campaign (§14.5). Campaign ICP rules, exclusions, geography,
and volume caps live in `CampaignPolicyVersion` (`T-015`) and are **not** duplicated here. Do not
merge the two: one is answerable to a campaign owner, the other is not.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, declared_attr, mapped_column

from app.core.settings import ModelProvider
from app.db.base import Base, TimestampMixin


def content_hash(payload: object) -> str:
    """Stable hash of a version's content.

    JSON with sorted keys so an equivalent object always hashes the same, and a changed one never
    does. Callers pass whatever defines the version — a prompt template, a JSON Schema, a model
    configuration.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class VersionedArtefact(TimestampMixin):
    """Shared shape: a stable key, an incrementing version, a content hash, and a window."""

    @declared_attr.directive
    def __tablename__(cls) -> str:
        raise NotImplementedError

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: Stable across versions: v1 and v2 of the same artefact share a key.
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: NULL means it runs until something supersedes it.
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    #: Identity string until T-012's user table exists; T-136 converts it.
    created_by: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)

    def is_effective_at(self, moment: datetime) -> bool:
        if moment < self.effective_from:
            return False
        return self.effective_to is None or moment < self.effective_to


def _shared_constraints(table: str) -> tuple[object, ...]:
    """Constraints every versioned artefact needs, named per table."""
    return (
        UniqueConstraint("key", "version", name=f"uq_{table}_key_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("length(trim(key)) > 0", name="key_not_blank"),
        CheckConstraint("length(trim(created_by)) > 0", name="created_by_not_blank"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_is_sha256_hex"),
        CheckConstraint(
            "effective_to IS NULL OR effective_to > effective_from",
            name="effective_window_ordered",
        ),
        Index(f"ix_{table}_key", "key"),
    )


class PromptVersion(Base, VersionedArtefact):
    """One version of one bounded model task's prompt (§18.4, §19.3 prompt regression)."""

    __tablename__ = "prompt_version"
    __table_args__ = _shared_constraints("prompt_version")

    #: Which bounded task this prompt serves, e.g. qualification or drafting.
    task_name: Mapped[str] = mapped_column(String(100), nullable=False)
    template: Mapped[str] = mapped_column(Text, nullable=False)

    def __repr__(self) -> str:
        return f"PromptVersion({self.key} v{self.version})"


class SchemaVersion(Base, VersionedArtefact):
    """One version of a JSON Schema that model output must satisfy (§10.4, §23)."""

    __tablename__ = "schema_version"
    __table_args__ = _shared_constraints("schema_version")

    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return f"SchemaVersion({self.key} v{self.version})"


class ModelConfigVersion(Base, VersionedArtefact):
    """One version of which model is used and how (§18.4, ADR-017).

    "Keep model names and provider endpoints in configuration, not business logic" (§18.4). This
    table *is* that configuration: business logic reads a version, never a literal model name.
    Only the deterministic fake exists until gate **G-03** and `Q-012`.
    """

    __tablename__ = "model_config_version"
    __table_args__ = _shared_constraints("model_config_version")

    provider: Mapped[ModelProvider] = mapped_column(nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Temperature, max tokens, and anything else that changes what the model does.
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    def __repr__(self) -> str:
        return f"ModelConfigVersion({self.provider.value}/{self.model_name} v{self.version})"


class PolicyVersion(Base, VersionedArtefact):
    """One version of a **global** policy (§14.5).

    Messaging guidance, objection handling, and similar rules that are not scoped to a campaign.
    Campaign ICP, exclusions, geography, and volume caps are `CampaignPolicyVersion` (`T-015`).
    """

    __tablename__ = "policy_version"
    __table_args__ = _shared_constraints("policy_version")

    policy_type: Mapped[str] = mapped_column(String(100), nullable=False)
    body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    def __repr__(self) -> str:
        return f"PolicyVersion({self.policy_type}/{self.key} v{self.version})"


#: Every versioned artefact type, for generic resolution and for tests that must cover them all.
VERSIONED_MODELS: tuple[type[VersionedArtefact], ...] = (
    PromptVersion,
    SchemaVersion,
    ModelConfigVersion,
    PolicyVersion,
)


class VersionNotFound(Exception):
    """No effective version exists for a key at the requested instant."""


def effective_version[T: VersionedArtefact](
    session: Session,
    model: type[T],
    key: str,
    *,
    at: datetime | None = None,
) -> T | None:
    """The one version of ``key`` in force at ``at``.

    The exclusion constraint guarantees at most one row can match, so this cannot silently choose
    between two overlapping versions.
    """
    moment = at or datetime.now(UTC)
    statement = (
        select(model)
        .where(model.key == key, model.effective_from <= moment)
        .where((model.effective_to.is_(None)) | (model.effective_to > moment))
    )
    return session.execute(statement).scalar_one_or_none()


def require_effective_version[T: VersionedArtefact](
    session: Session,
    model: type[T],
    key: str,
    *,
    at: datetime | None = None,
) -> T:
    """As :func:`effective_version`, but raises.

    Used where a model run is about to happen: running against no known prompt or schema version
    would produce a result nobody can later explain (§17.5).
    """
    found = effective_version(session, model, key, at=at)
    if found is None:
        moment = at or datetime.now(UTC)
        raise VersionNotFound(
            f"no effective {model.__name__} for key {key!r} at {moment.isoformat()}; "
            f"every model run must be attributable to exact versions (§17.5)"
        )
    return found
