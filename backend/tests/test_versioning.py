"""Every decision is attributable to exact versions (T-023; §14.1, §17.5, GP-09).

The point of these tables is that a decision made weeks ago can still be explained by reading
what produced it. That only holds if a version cannot be edited after the fact and if exactly one
version is ever in force for a key at a given instant.
"""

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import (
    VERSIONED_MODELS,
    ModelConfigVersion,
    PolicyVersion,
    PromptVersion,
    SchemaVersion,
    VersionedArtefact,
    VersionNotFound,
    content_hash,
    effective_version,
    require_effective_version,
)
from app.core.settings import ModelProvider

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=30)
LATER = NOW + timedelta(days=30)
APP = Path(__file__).resolve().parents[1] / "app"


def make(model: type[VersionedArtefact], **overrides: object) -> VersionedArtefact:
    common: dict[str, object] = {
        "key": f"synthetic-{uuid.uuid4().hex[:8]}",
        "version": 1,
        "content_hash": content_hash({"synthetic": True}),
        "effective_from": EARLIER,
        "effective_to": None,
        "created_by": "author-1",
    }
    specific: dict[type[VersionedArtefact], dict[str, object]] = {
        PromptVersion: {"task_name": "qualification", "template": "SYNTHETIC prompt"},
        SchemaVersion: {"json_schema": {"type": "object"}},
        ModelConfigVersion: {
            "provider": ModelProvider.FAKE,
            "model_name": "deterministic-fake",
            "parameters": {},
        },
        PolicyVersion: {"policy_type": "objection_handling", "body": {"rules": []}},
    }
    common.update(specific[model])
    common.update(overrides)
    return model(**common)  # type: ignore[operator]


@pytest.mark.parametrize("model", VERSIONED_MODELS, ids=lambda m: m.__name__)
class TestEveryVersionedArtefact:
    """The same guarantees must hold for all four tables, so every test runs against each."""

    def test_it_can_be_written_and_read_back(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        artefact = make(model)
        db_session.add(artefact)
        db_session.flush()

        assert effective_version(db_session, model, artefact.key, at=NOW) is not None

    def test_the_content_cannot_be_rewritten(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        """Editing in place would rewrite the basis of every run that already cites it."""
        artefact = make(model)
        db_session.add(artefact)
        db_session.flush()

        with pytest.raises(DBAPIError) as exc:
            db_session.execute(
                text(
                    f"UPDATE {model.__tablename__} SET content_hash = repeat('b', 64) "  # type: ignore[attr-defined]
                    "WHERE id = :id"
                ),
                {"id": artefact.id},
            )

        assert "immutable" in str(exc.value)

    def test_the_author_cannot_be_rewritten(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        artefact = make(model)
        db_session.add(artefact)
        db_session.flush()

        artefact.created_by = "someone-else"

        with pytest.raises(DBAPIError):
            db_session.flush()

    def test_closing_the_window_is_allowed(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        """Closing a window is how the next version takes over; it changes no content."""
        artefact = make(model)
        db_session.add(artefact)
        db_session.flush()

        artefact.effective_to = NOW
        db_session.flush()  # must not raise

        assert artefact.effective_to == NOW

    def test_two_overlapping_versions_are_rejected(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        """Two 'current' versions would make a model run unattributable."""
        key = f"synthetic-{uuid.uuid4().hex[:8]}"
        db_session.add(make(model, key=key, version=1, effective_from=EARLIER))
        db_session.flush()
        db_session.add(make(model, key=key, version=2, effective_from=NOW))

        with pytest.raises(IntegrityError) as exc:
            db_session.flush()

        assert "no_overlap" in str(exc.value)

    def test_a_clean_handover_is_allowed(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        key = f"synthetic-{uuid.uuid4().hex[:8]}"
        db_session.add(make(model, key=key, version=1, effective_from=EARLIER, effective_to=NOW))
        db_session.add(make(model, key=key, version=2, effective_from=NOW))

        db_session.flush()  # must not raise

        current = effective_version(db_session, model, key, at=NOW)
        assert current is not None
        assert current.version == 2

    def test_version_numbers_are_unique_per_key(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        key = f"synthetic-{uuid.uuid4().hex[:8]}"
        db_session.add(make(model, key=key, version=1, effective_from=EARLIER, effective_to=NOW))
        db_session.flush()
        db_session.add(make(model, key=key, version=1, effective_from=NOW))

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_an_expired_version_is_not_current(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        artefact = make(model, effective_from=EARLIER, effective_to=NOW)
        db_session.add(artefact)
        db_session.flush()

        assert effective_version(db_session, model, artefact.key, at=LATER) is None
        assert not artefact.is_effective_at(LATER)

    def test_requiring_a_missing_version_raises(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        """Running against no known version produces a result nobody can explain (§17.5)."""
        with pytest.raises(VersionNotFound) as exc:
            require_effective_version(db_session, model, "absent-key", at=NOW)

        assert model.__name__ in str(exc.value)

    def test_a_malformed_hash_is_rejected(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        db_session.add(make(model, content_hash="not-a-hash"))

        with pytest.raises(IntegrityError):
            db_session.flush()

    def test_a_backwards_window_is_rejected(
        self, model: type[VersionedArtefact], db_session: Session
    ) -> None:
        db_session.add(make(model, effective_from=LATER, effective_to=EARLIER))

        with pytest.raises(IntegrityError):
            db_session.flush()


# --- the content hash (criterion 2) --------------------------------------------------------


def test_the_hash_changes_with_the_content() -> None:
    assert content_hash({"template": "a"}) != content_hash({"template": "b"})


def test_the_hash_is_stable_for_equivalent_content() -> None:
    """Key order must not change the hash, or an unchanged version would look edited."""
    assert content_hash({"a": 1, "b": 2}) == content_hash({"b": 2, "a": 1})


def test_the_hash_notices_a_nested_change() -> None:
    assert content_hash({"outer": {"inner": 1}}) != content_hash({"outer": {"inner": 2}})


# --- model configuration is configuration (criterion 3) --------------------------------------


def test_the_model_config_holds_provider_and_model(db_session: Session) -> None:
    config = make(ModelConfigVersion)
    db_session.add(config)
    db_session.flush()

    assert isinstance(config.provider, ModelProvider)  # type: ignore[attr-defined]
    assert config.model_name == "deterministic-fake"  # type: ignore[attr-defined]


def test_only_the_fake_provider_exists() -> None:
    """A real provider requires gate G-03 and `Q-012` (ADR-017)."""
    assert [p.value for p in ModelProvider] == ["fake"]


def test_no_model_identifier_is_hard_coded_in_business_logic() -> None:
    """§18.4: "keep model names and provider endpoints in configuration, not business logic"."""
    vendor_markers = ("claude-", "gpt-4", "gpt-5", "deepseek", "api.openai.com", "api.anthropic")
    offenders: list[str] = []

    for path in APP.rglob("*.py"):
        lowered = path.read_text(encoding="utf-8").lower()
        offenders.extend(
            f"{path.relative_to(APP)}: {marker}" for marker in vendor_markers if marker in lowered
        )

    assert not offenders, f"model identifiers belong in configuration, not code: {offenders}"


# --- coverage of the specification's entity list -----------------------------------------------


def test_all_four_versioned_entities_exist() -> None:
    """§14.1 names exactly these four under Versioning."""
    assert {m.__name__ for m in VERSIONED_MODELS} == {
        "PromptVersion",
        "SchemaVersion",
        "ModelConfigVersion",
        "PolicyVersion",
    }


def test_global_policy_is_distinct_from_campaign_policy(db_session: Session) -> None:
    """`CampaignPolicyVersion` (T-015) is campaign-scoped; `PolicyVersion` is not. Do not merge."""
    from app.campaigns.models import CampaignPolicyVersion

    assert CampaignPolicyVersion.__tablename__ != PolicyVersion.__tablename__
    assert not hasattr(PolicyVersion, "campaign_id")
    assert hasattr(CampaignPolicyVersion, "campaign_id")
