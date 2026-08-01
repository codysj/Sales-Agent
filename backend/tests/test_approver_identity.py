"""An approver is a user, and a user with history cannot be deleted (T-136b, T-136c; §14.4, §12.2).

Two things, and the second is the one that matters. The first is that all five approver columns
really carry the constraint — asserted against the **database**, because the schema under test is
built from migrations and a model attribute nobody migrated would be a lie. The second is that
`RESTRICT` behaves: §12.2 requires attribution to be immutable, and an approval whose approver row
was deleted is attribution nobody can follow.

The foreign key targets `app_user.email` rather than `app_user.id` (ADR-024): the email is what
the production path already records, and keeping it in the column means the row still says *who*
without a join.
"""

import ast
import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import structlog
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.models import CampaignPolicyVersion
from app.drafts_and_approvals.approval import request_approval
from app.identity.models import User
from app.products_and_claims.claim_models import (
    ApprovedClaim,
    ApprovedClaimCampaign,
    ApprovedClaimSet,
)
from app.products_and_claims.claims import publish_claim_set
from app.products_and_claims.models import ProductStatusVersion, ReadinessCategory
from tests.factories import APPROVER, NOW, OPERATOR, OWNER_TWO, World

#: The migration module, loaded by path: `alembic/versions/` is not a package, and the pre-flight
#: check inside it is the thing two tests below exercise directly.
_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "c41d7b90ae52_approver_foreign_keys.py"
)
_APPROVAL_MIGRATION_PATH = _MIGRATION_PATH.with_name(
    "d83b2f16c907_approval_approver_foreign_key.py"
)


def _load(path: Path, name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION = _load(_MIGRATION_PATH, "t136b_migration")
_APPROVAL_MIGRATION = _load(_APPROVAL_MIGRATION_PATH, "t136c_migration")
unresolvable_approvers = _MIGRATION.unresolvable_approvers  # type: ignore[attr-defined]
unresolvable_approval_approvers = (
    _APPROVAL_MIGRATION.unresolvable_approvers  # type: ignore[attr-defined]
)

#: The table the pre-flight tests use. One is enough: the check walks all four from the same list.
TABLE = "product_status_version"

#: table -> (column, constraint). Named per table so a violation says which record refused,
#: rather than one shared name on five tables. `approval` is the odd one out in two ways: its
#: column is `approver_id` rather than `approved_by`, and it is the only one with an HTTP surface
#: (`T-136c`) — the review API writes `principal.user.email` into it.
APPROVER_TABLES = {
    "product_status_version": ("approved_by", "fk_product_status_version_approved_by_app_user"),
    "approved_claim": ("approved_by", "fk_approved_claim_approved_by_app_user"),
    "approved_claim_set": ("approved_by", "fk_approved_claim_set_approved_by_app_user"),
    "campaign_policy_version": ("approved_by", "fk_campaign_policy_version_approved_by_app_user"),
    "approval": ("approver_id", "fk_approval_approver_id_app_user"),
}


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-approver-identity-test")


# --- criterion 1: the constraint exists, on all four -------------------------------------------


@pytest.mark.parametrize("table", sorted(APPROVER_TABLES), ids=lambda name: name)
def test_the_approver_column_is_a_foreign_key_to_a_user(db_session: Session, table: str) -> None:
    """Read out of the live schema, not off the model: the tests build from migrations."""
    column, _ = APPROVER_TABLES[table]
    keys = inspect(db_session.get_bind()).get_foreign_keys(table)
    approver = [key for key in keys if key["constrained_columns"] == [column]]

    assert approver, f"{table}.{column} carries no foreign key"
    assert approver[0]["referred_table"] == "app_user"
    assert approver[0]["referred_columns"] == ["email"]


@pytest.mark.parametrize("table", sorted(APPROVER_TABLES), ids=lambda name: name)
def test_the_approver_foreign_key_restricts_deletion(db_session: Session, table: str) -> None:
    # `RESTRICT` rather than `CASCADE` or `SET NULL` is the whole point. The option lives in the
    # catalogue, so a migration that created the key with the wrong rule fails here.
    rule = db_session.execute(
        text("SELECT confdeltype FROM pg_constraint WHERE conname = :name"),
        {"name": APPROVER_TABLES[table][1]},
    ).scalar_one()

    assert rule == "r", f"{table}'s approver key deletes with rule {rule!r}, not RESTRICT"


def test_an_unknown_approver_is_refused(db_session: Session) -> None:
    """The typo case, which is the reason `T-136` exists at all."""
    world = World(db_session)

    db_session.add(
        ProductStatusVersion(
            product_id=world.product.id,
            version=99,
            readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
            summary="SYNTHETIC status",
            approved_by="nobody@example.invalid",
            approved_at=NOW,
            effective_from=NOW,
            expires_or_review_by=None,
        )
    )
    with pytest.raises(IntegrityError, match="approved_by"):
        db_session.flush()


def test_the_migration_refuses_an_approver_it_cannot_resolve(db_session: Session) -> None:
    """The pre-flight that stops the migration rather than nulling attribution (§12.2).

    Reachable only where the constraint is absent — which is the state the migration runs in — so
    the test drops one inside its own transaction, writes the row the constraint would have
    refused, and asks the check. Everything here is rolled back with the session.

    Written because a control that removed the pre-flight call passed: nothing covered it, since
    a test database is always empty and the check only fires on a database that already has rows.
    """
    connection = db_session.connection()
    connection.execute(
        text(f"ALTER TABLE product_status_version DROP CONSTRAINT {APPROVER_TABLES[TABLE][1]}")
    )
    world = World(db_session)
    db_session.add(
        ProductStatusVersion(
            product_id=world.product.id,
            version=99,
            readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
            summary="SYNTHETIC status",
            approved_by="nobody@example.invalid",
            approved_at=NOW,
            effective_from=NOW,
            expires_or_review_by=None,
        )
    )
    db_session.flush()

    assert unresolvable_approvers(connection) == {TABLE: ["nobody@example.invalid"]}


@pytest.mark.parametrize(
    "migration",
    [_MIGRATION_PATH, _APPROVAL_MIGRATION_PATH],
    ids=lambda path: path.stem[:12],
)
def test_the_migration_runs_the_check_before_it_adds_the_constraints(migration: Path) -> None:
    """That the check *works* is above; this is that `upgrade` still calls it, and calls it first.

    Structural rather than behavioural, because the behaviour needs a database holding rows the
    constraint forbids — reachable only by running the migration on somebody's existing database,
    which no test can stand up. Without this, deleting the call from `upgrade()` passed every
    test in this file, and the failure would have surfaced as a bare foreign-key violation naming
    a constraint the reader has never heard of.
    """
    tree = ast.parse(migration.read_text(encoding="utf-8"))
    upgrade = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "upgrade"
    )
    calls = [
        node.func.id
        for statement in upgrade.body
        for node in ast.walk(statement)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]

    assert "_refuse_unresolvable_approvers" in calls, "upgrade() no longer runs the pre-flight"
    assert calls[0] == "_refuse_unresolvable_approvers", (
        f"upgrade() does something before the pre-flight: {calls}"
    )


def test_the_migration_check_is_quiet_when_every_approver_resolves(db_session: Session) -> None:
    """The other half: a check that always reported something would stop every migration."""
    World(db_session)

    assert unresolvable_approvers(db_session.connection()) == {}


# --- T-136c: the approval's approver, the one with an HTTP surface -----------------------------


def test_an_approval_cannot_name_an_approver_who_is_not_a_user(db_session: Session) -> None:
    """The same typo guard, on the column a reviewer's decision actually lands in."""
    world = World(db_session)

    with pytest.raises(IntegrityError, match="approver_id"):
        request_approval(
            db_session,
            revision=world.revision,
            approver_id="nobody@example.invalid",
            actor=OPERATOR,
            now=NOW,
        )
        db_session.flush()
    db_session.rollback()


def test_deleting_a_user_who_holds_an_approval_is_refused(db_session: Session) -> None:
    """§12.2 again, and this is the attribution a send is performed on the strength of."""
    # Approved by `OWNER_TWO`, who has no other history in this world. `APPROVER` would have been
    # refused by `campaign_policy_version`'s key first, and the test would have passed without the
    # approval column ever being consulted.
    world = World(db_session)
    request_approval(
        db_session, revision=world.revision, approver_id=OWNER_TWO, actor=OPERATOR, now=NOW
    )
    db_session.flush()

    approver = db_session.execute(select(User).where(User.email == OWNER_TWO)).scalar_one()
    db_session.delete(approver)
    with pytest.raises(IntegrityError, match="fk_approval_approver_id_app_user"):
        db_session.flush()
    db_session.rollback()


def test_the_approval_migration_check_finds_an_unresolvable_approver(db_session: Session) -> None:
    """Its own pre-flight, reachable only with the constraint dropped — see the T-136b twin."""
    connection = db_session.connection()
    connection.execute(
        text(f"ALTER TABLE approval DROP CONSTRAINT {APPROVER_TABLES['approval'][1]}")
    )
    world = World(db_session)
    request_approval(
        db_session,
        revision=world.revision,
        approver_id="nobody@example.invalid",
        actor=OPERATOR,
        now=NOW,
    )
    db_session.flush()

    assert unresolvable_approval_approvers(connection) == ["nobody@example.invalid"]


def test_the_approval_migration_check_is_quiet_when_the_approver_resolves(
    db_session: Session,
) -> None:
    world = World(db_session)
    world.approval()
    db_session.flush()

    assert unresolvable_approval_approvers(db_session.connection()) == []


# --- criterion 2: an approver with history survives a delete attempt ---------------------------


def test_deleting_a_user_who_approved_something_is_refused(db_session: Session) -> None:
    """§12.2. Deactivation is the supported move; deletion is not, and the database says so."""
    world = World(db_session)  # publishes a campaign policy version approved by APPROVER
    approver = db_session.execute(select(User).where(User.email == APPROVER)).scalar_one()

    db_session.delete(approver)
    with pytest.raises(IntegrityError, match="campaign_policy_version"):
        db_session.flush()
    db_session.rollback()

    assert world is not None  # the world outlives the refused delete


def test_every_approver_column_holds_the_key_open(db_session: Session) -> None:
    """One row per table, all four naming the same user, then one delete attempt.

    Parametrizing this would build four worlds to prove one property; what matters is that *no*
    column lets go, so all four are populated before the delete is tried.
    """
    world = World(db_session)
    moment = datetime.now(UTC) - timedelta(minutes=1)

    db_session.add(
        ProductStatusVersion(
            product_id=world.product.id,
            version=99,
            readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
            summary="SYNTHETIC status",
            approved_by=OWNER_TWO,
            approved_at=moment,
            effective_from=moment,
            expires_or_review_by=None,
        )
    )
    claim = ApprovedClaim(
        claim_key=f"synthetic-claim-{uuid.uuid4().hex[:8]}",
        version=1,
        product_id=world.product.id,
        text="SYNTHETIC claim text.",
        presumes_readiness=ReadinessCategory.EVALUATION_OR_PILOT,
        approved_by=OWNER_TWO,
        approved_at=moment,
        effective_from=moment,
        expires_or_review_by=moment + timedelta(days=180),
    )
    db_session.add(claim)
    db_session.flush()
    # A set may only carry claims allow-listed for the campaign (`T-014`).
    db_session.add(ApprovedClaimCampaign(claim_id=claim.id, campaign_id=world.campaign.id))
    db_session.flush()
    publish_claim_set(
        db_session,
        product_id=world.product.id,
        campaign_id=world.campaign.id,
        claims=[claim],
        approved_by=OWNER_TWO,
        approved_at=moment,
    )
    db_session.flush()

    populated = {
        "product_status_version": ProductStatusVersion,
        "approved_claim": ApprovedClaim,
        "approved_claim_set": ApprovedClaimSet,
    }
    for name, model in populated.items():
        rows = (
            db_session.execute(
                select(model).where(model.approved_by == OWNER_TWO)  # type: ignore[attr-defined]
            )
            .scalars()
            .all()
        )
        assert rows, f"{name} was not populated, so the delete below would prove nothing"
    assert (
        db_session.execute(
            select(CampaignPolicyVersion).where(CampaignPolicyVersion.approved_by == APPROVER)
        )
        .scalars()
        .all()
    )

    owner = db_session.execute(select(User).where(User.email == OWNER_TWO)).scalar_one()
    db_session.delete(owner)
    with pytest.raises(IntegrityError):
        db_session.flush()
