"""The shared test clock must not expire (T-142; specification §8.4, §23).

`tests/factories.NOW` used to be the literal `2026-07-27 12:00 UTC`, copied into twelve more test
modules. `Approval` carries `CHECK (approval_expires_at > created_at)` and `created_at` comes
from the server clock, so once real time passed `NOW + DEFAULT_APPROVAL_TTL` every approval the
factories built became un-insertable: 89 tests went from green to red between two runs on the
same day with no code change between them.

The fix belongs in the fixtures, never in the constraint — an approval that expires before it was
created is exactly the row the database should refuse. So this module guards both ends:

* the clock keeps a real margin on both sides, and no module re-introduces a literal;
* the constraint that caught the problem is still in the migration and still bites.
"""

import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.drafts_and_approvals.approval import DEFAULT_APPROVAL_TTL, Approval
from tests.conftest import BACKEND
from tests.factories import NOW, World

#: The migration that created `approval`, and the constraint this task must not weaken.
APPROVAL_MIGRATION = BACKEND / "alembic" / "versions" / "0133f6adb316_approval.py"
EXPIRY_CONSTRAINT = "approval_expires_at > created_at"

TESTS = Path(__file__).resolve().parent


@pytest.fixture(autouse=True)
def _correlation() -> None:
    """`World` records audit events, and an event with no correlation ID is refused (§17.5)."""
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-fixture-clock-test")


# --- the clock cannot go stale (criterion 2) ------------------------------------------------


def test_an_approval_built_at_the_fixture_clock_still_has_a_future_expiry() -> None:
    """The exact arithmetic that broke: `NOW + TTL` must stay ahead of the server clock."""
    assert datetime.now(UTC) < NOW + DEFAULT_APPROVAL_TTL


def test_the_fixture_clock_keeps_a_margin_on_both_sides() -> None:
    """Not just "not expired": a margin, so a slow suite cannot cross the line mid-run."""
    moment = datetime.now(UTC)

    assert moment - NOW >= timedelta(hours=24), "NOW must stay comfortably in the past"
    assert (NOW + DEFAULT_APPROVAL_TTL) - moment >= timedelta(hours=24), "expiry margin too thin"


def test_the_clock_is_derived_rather_than_written_down() -> None:
    """A literal is what rotted last time; `NOW` must be computed from the current time."""
    source = (TESTS / "factories.py").read_text(encoding="utf-8")
    declaration = next(line for line in source.splitlines() if line.startswith("NOW ="))

    assert "datetime.now(" in declaration, f"NOW is not derived from the clock: {declaration}"


def test_no_test_module_declares_its_own_clock() -> None:
    """Twelve copies of one literal is why a single stale date could redden 89 tests."""
    offenders = [
        path.name
        for path in sorted(TESTS.glob("test_*.py"))
        if path.name != Path(__file__).name
        and re.search(r"^NOW\s*=", path.read_text(encoding="utf-8"), re.MULTILINE)
    ]

    assert not offenders, f"modules redeclaring NOW instead of importing it: {offenders}"


# --- the constraint that caught it is untouched (criterion 1) --------------------------------


def test_the_migration_still_carries_the_expiry_constraint() -> None:
    """Structural, not behavioural: the fix must not have quietly relaxed the schema."""
    migration = APPROVAL_MIGRATION.read_text(encoding="utf-8")

    assert EXPIRY_CONSTRAINT in migration
    assert "ck_approval_expiry_after_creation" in migration


def test_the_model_and_the_migration_agree_on_the_constraint() -> None:
    constraints = {
        constraint.name: str(constraint.sqltext)
        for constraint in Approval.__table__.constraints
        if hasattr(constraint, "sqltext")
    }

    assert constraints.get("ck_approval_expiry_after_creation") == EXPIRY_CONSTRAINT


def test_the_database_refuses_an_approval_that_expired_before_it_was_created(
    db_session: Session,
) -> None:
    """Criterion 3: a deliberately past expiry, proving the constraint still bites."""
    world = World(db_session)
    db_session.add(
        Approval(
            message_revision_id=world.revision.id,
            recipient_contact_point_id=world.recipient.id,
            approver_id="approver-1",
            approval_expires_at=datetime.now(UTC) - timedelta(days=1),
            approved_content_hash="a" * 64,
        )
    )

    with pytest.raises(IntegrityError, match="ck_approval_expiry_after_creation"):
        db_session.flush()
