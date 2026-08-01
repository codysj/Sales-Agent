"""Actor columns record an actor, not a user (T-166; ADR-025, §12.2).

An ADR nobody can find from the code is a decision that gets re-made. So the check is not "does
the ADR exist" — it is that every column the ADR decides **says so where a reader is standing**,
and that none of them has quietly acquired the foreign key the ADR rejected.

Offline: this reads source and model metadata, and needs no database.
"""

import uuid
from pathlib import Path

import pytest
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import OperationalFlag
from app.audit_and_operations.models import AuditEvent
from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    PolicyVersion,
    PromptVersion,
    SchemaVersion,
)
from app.campaigns.decisions import CandidateDecision
from app.db.base import Base
from app.drafts_and_approvals.models import MessageRevision
from app.identity.models import ServiceIdentityRole, User, UserRole
from app.identity.sessions import Principal, UserSession, issue_session
from app.outreach_and_replies.models import SendCommand
from app.prospects.suppression import Suppression
from tests.factories import World, a_user

APP = Path(__file__).resolve().parents[1] / "app"

#: The decision's subject: (model, column). The seven `T-166` named — `created_by` is declared
#: once on the `VersionedArtefact` mixin and inherited by four tables, all listed so the *table*
#: is checked and not only the source line — plus the two columns that carried a stale
#: "T-136 converts it" comment after `T-136` closed without converting them.
ACTOR_COLUMNS = [
    (OperationalFlag, "set_by"),
    (PromptVersion, "created_by"),
    (SchemaVersion, "created_by"),
    (ModelConfigVersion, "created_by"),
    (PolicyVersion, "created_by"),
    (CandidateDecision, "decided_by"),
    (UserSession, "revoked_by"),
    (Suppression, "lifted_by"),
    (UserRole, "granted_by"),
    (ServiceIdentityRole, "granted_by"),
    (MessageRevision, "created_by"),
    (SendCommand, "actor_id"),
]

#: `audit_event.actor_id` is the precedent ADR-025 generalizes, and is deliberately not annotated
#: with it — its own docstring already carries the reason. Listed so the walk below can prove it
#: still takes no foreign key either.
PRECEDENT = (AuditEvent, "actor_id")

#: How far above a column definition the decision may be recorded before a reader stops seeing it.
COMMENT_WINDOW = 8


def _source_of(model: type[Base]) -> tuple[Path, str]:
    path = Path(str(model.__module__).replace(".", "/") + ".py")
    resolved = APP.parents[0] / path
    return resolved, resolved.read_text(encoding="utf-8")


def _records_the_decision(model: type[Base], column: str) -> bool:
    """Does ADR-025 appear in the comment block immediately above this column?"""
    _, source = _source_of(model)
    lines = source.splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{column}: Mapped["):
            window = lines[max(0, index - COMMENT_WINDOW) : index]
            if any("ADR-025" in entry for entry in window):
                return True
    return False


@pytest.mark.parametrize(
    ("model", "column"),
    ACTOR_COLUMNS,
    ids=[f"{model.__tablename__}.{column}" for model, column in ACTOR_COLUMNS],
)
def test_the_column_says_which_decision_governs_it(model: type[Base], column: str) -> None:
    # Criterion 2. Where the reader is standing, not in a document they would have to know about.
    assert _records_the_decision(model, column), (
        f"{model.__tablename__}.{column} does not name ADR-025 within {COMMENT_WINDOW} lines"
    )


@pytest.mark.parametrize(
    ("model", "column"),
    [*ACTOR_COLUMNS, PRECEDENT],
    ids=[f"{m.__tablename__}.{c}" for m, c in [*ACTOR_COLUMNS, PRECEDENT]],
)
def test_the_column_takes_no_foreign_key(model: type[Base], column: str) -> None:
    """The decision itself, asserted against the mapping rather than the prose.

    A future change that adds the nullable key ADR-025 rejected would otherwise land with the
    comment still saying it was rejected — which is worse than no comment.
    """
    keys = model.__table__.c[column].foreign_keys

    assert not keys, (
        f"{model.__tablename__}.{column} acquired a foreign key to "
        f"{sorted(key.target_fullname for key in keys)}; ADR-025 rejected exactly that"
    )


def test_the_check_can_fail() -> None:
    """The detector fires, rather than merely existing: `Approval.approver_id` is keyed (ADR-024)
    and carries no ADR-025 comment, so both checks above must reject it."""
    from app.drafts_and_approvals.approval import Approval

    assert not _records_the_decision(Approval, "approver_id")
    assert Approval.__table__.c["approver_id"].foreign_keys


# --- T-167 / ADR-026: two vocabularies, and neither may drift into the other -------------------


def _principal_for(session: Session, user: User) -> Principal:
    """A principal with a real session behind it — `Actor` is derived, never supplied."""
    issued = issue_session(session, user, issued_via="test")
    return Principal(user=user, session=issued.session, roles=frozenset())


def test_the_actor_vocabulary_is_an_opaque_id(db_session: Session) -> None:
    """`Principal.actor.id` is the user's UUID, never their email (ADR-026).

    The actor is the field that ends up in log lines, and §15.5 asks for contacts to be redacted
    from logs. That holds only while this value is opaque — so the assertion is not "it equals the
    id" alone but "it is not an address", which is what a future one-line change would break.
    """
    user = a_user(db_session, "synthetic-vocabulary@example.invalid", "SYNTHETIC-Vocabulary")
    principal = _principal_for(db_session, user)

    assert principal.actor.id == str(user.id)
    assert uuid.UUID(principal.actor.id) == user.id, "the actor id is not an opaque identifier"
    assert "@" not in principal.actor.id, "the actor id became a contact address (§15.5)"


def test_the_approver_vocabulary_is_the_email(db_session: Session) -> None:
    """The other side of the rule: an approval names a user by address, not by id (ADR-024)."""
    # `World` records audit events, and every consequential action needs a correlation id (§17.5).
    with structlog.contextvars.bound_contextvars(correlation_id="corr-actor-columns-test"):
        world = World(db_session)
        approval = world.approval()

    assert "@" in approval.approver_id, "the approver stopped being an address"
    assert (
        db_session.execute(
            select(User).where(User.email == approval.approver_id)
        ).scalar_one_or_none()
        is not None
    )


def test_the_route_that_approves_writes_the_approver_vocabulary() -> None:
    """The writer, structurally: `principal.user.email`, not `principal.actor.id`.

    A source check because the alternative is an end-to-end approval through HTTP, which
    `tests/test_approval_transaction.py` already owns. What is needed here is that the *choice* of
    vocabulary at the one place both are in scope cannot flip unnoticed.
    """
    source = (APP / "outreach_and_replies" / "api.py").read_text(encoding="utf-8")

    assert "approver_id=principal.user.email," in source
    assert "approver_id=principal.actor.id" not in source


def test_the_two_vocabularies_describe_the_same_person(db_session: Session) -> None:
    """The join the split costs, written down once so the cost is visible rather than folklore."""
    user = a_user(db_session, "synthetic-both@example.invalid", "SYNTHETIC-Both")
    principal = _principal_for(db_session, user)

    by_actor = db_session.execute(
        select(User).where(User.id == uuid.UUID(principal.actor.id))
    ).scalar_one()
    by_approver = db_session.execute(select(User).where(User.email == user.email)).scalar_one()

    assert by_actor is by_approver


def test_the_adr_is_indexed() -> None:
    index = (APP.parents[1] / "docs" / "adr" / "README.md").read_text(encoding="utf-8")

    assert "ADR-025" in index, "ADR-025 is not in the local ADR index"
    assert "ADR-026" in index, "ADR-026 is not in the local ADR index"
