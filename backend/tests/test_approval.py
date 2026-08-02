"""An approval authorizes exactly what it authorized (T-021; §8.4, §11.3, §11.4, ADR-008).

§8.4 lists six things that invalidate an approval: a changed recipient, subject, body, material
personalization fact, product status, or claim version. There is one test per trigger, plus the
rules that an approval names one immutable revision and that a closed approval never reopens.
"""

import uuid
from datetime import timedelta

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate
from app.campaigns.models import Campaign
from app.core.lifecycles import ApprovalState, IllegalTransition
from app.drafts_and_approvals.approval import (
    DEFAULT_APPROVAL_TTL,
    Approval,
    ApprovalAlreadyClosed,
    ApprovalError,
    ApprovalNotValid,
    RevocationNeedsReason,
    approve,
    expire,
    invalidation_reason,
    is_valid,
    live_approval,
    reject,
    request_approval,
    require_valid,
    revoke,
)
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.drafts_and_approvals.revisions import create_revision
from app.products_and_claims.claim_models import ApprovedClaimSet
from app.products_and_claims.models import (
    Product,
    ProductStatusVersion,
    ReadinessCategory,
)
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType
from tests.factories import APPROVER, CLAIM_OWNER, NOW, OWNER_TWO, PRODUCT_OWNER

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
LATER = NOW + timedelta(days=30)


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-approval-test")


class World:
    """The objects an approval pins together."""

    def __init__(self, session: Session) -> None:
        self.product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
        session.add(self.product)
        session.flush()

        self.campaign = Campaign(
            slug=f"synthetic-{uuid.uuid4().hex[:8]}",
            name="SYNTHETIC-Campaign",
            product_id=self.product.id,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account"
        )
        session.add_all([self.campaign, self.account])
        session.flush()

        self.contact = Contact(account_id=self.account.id, full_name="SYNTHETIC Person")
        session.add(self.contact)
        session.flush()

        self.recipient = ContactPoint(
            contact_id=self.contact.id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@example.com",
        )
        session.add(self.recipient)
        session.flush()

        self.candidate = create_candidate(
            session,
            campaign_id=self.campaign.id,
            account_id=self.account.id,
            contact_id=self.contact.id,
            actor=OPERATOR,
        )
        self.draft = MessageDraft(candidate_id=self.candidate.id)
        session.add(self.draft)
        session.flush()

        self.status = ProductStatusVersion(
            product_id=self.product.id,
            version=1,
            readiness_category=ReadinessCategory.EVALUATION_OR_PILOT,
            approved_by=PRODUCT_OWNER,
            approved_at=NOW - timedelta(days=1),
            effective_from=NOW - timedelta(days=1),
        )
        self.claim_set = ApprovedClaimSet(
            product_id=self.product.id,
            campaign_id=self.campaign.id,
            version=1,
            approved_by=CLAIM_OWNER,
            approved_at=NOW - timedelta(days=1),
        )
        session.add_all([self.status, self.claim_set])
        session.flush()

        self.evidence_id = uuid.uuid4()
        self.revision = self._revision(session)

    def _revision(self, session: Session, **overrides: object) -> MessageRevision:
        values: dict[str, object] = {
            "recipient_contact_point_id": self.recipient.id,
            "subject": "SYNTHETIC subject",
            "body": "SYNTHETIC body",
            "approved_claim_ids": [],
            "evidence_ids": [self.evidence_id],
            "created_by": "drafter-1",
        }
        values.update(overrides)
        return create_revision(session, draft=self.draft, actor=OPERATOR, **values)  # type: ignore[arg-type]

    def edit(self, session: Session, **overrides: object) -> MessageRevision:
        """Edit the message the way the dashboard would: a new revision supersedes the old."""
        return self._revision(session, **overrides)


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


def approved_approval(db_session: Session, world: World) -> Approval:
    approval = request_approval(
        db_session,
        revision=world.revision,
        approver_id=APPROVER,
        actor=OPERATOR,
        product_status_version_id=world.status.id,
        approved_claim_set_id=world.claim_set.id,
        now=NOW,
    )
    approve(db_session, approval, actor=OPERATOR, now=NOW)
    db_session.flush()
    return approval


# --- one immutable revision (criterion 1) ---------------------------------------------------


def test_an_approval_names_exactly_one_revision(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    assert approval.message_revision_id == world.revision.id


def test_an_approval_without_a_revision_is_impossible(db_session: Session, world: World) -> None:
    db_session.add(
        Approval(
            message_revision_id=None,
            recipient_contact_point_id=world.recipient.id,
            approver_id=APPROVER,
            approval_expires_at=LATER,
            approved_content_hash="a" * 64,
        )
    )

    with pytest.raises((IntegrityError, DBAPIError)):
        db_session.flush()


def test_the_approved_revision_cannot_be_deleted(db_session: Session, world: World) -> None:
    approved_approval(db_session, world)

    db_session.delete(world.revision)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_pinned_scope_cannot_be_repointed(db_session: Session, world: World) -> None:
    """Otherwise an approval could be quietly aimed at different content."""
    approval = approved_approval(db_session, world)

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("UPDATE approval SET approved_content_hash = repeat('b', 64) WHERE id = :id"),
            {"id": approval.id},
        )

    assert "immutable" in str(exc.value)


def test_only_one_live_approval_per_revision(db_session: Session, world: World) -> None:
    approved_approval(db_session, world)

    with pytest.raises(IntegrityError) as exc:
        request_approval(
            db_session, revision=world.revision, approver_id=OWNER_TWO, actor=OPERATOR, now=NOW
        )

    assert "uq_approval_live_per_revision" in str(exc.value)


def test_a_rejected_approval_frees_the_revision_for_a_new_request(
    db_session: Session, world: World
) -> None:
    """The uniqueness index is partial, so a closed approval does not block re-review."""
    first = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    reject(db_session, first, actor=OPERATOR, reason="tone", now=NOW)
    db_session.flush()

    second = request_approval(
        db_session, revision=world.revision, approver_id=OWNER_TWO, actor=OPERATOR, now=NOW
    )
    db_session.flush()

    assert live_approval(db_session, world.revision.id) is not None
    assert live_approval(db_session, world.revision.id).id == second.id  # type: ignore[union-attr]


# --- the six §8.4 invalidation triggers (criterion 2) ----------------------------------------


def test_a_changed_recipient_invalidates_the_approval(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)
    other = ContactPoint(
        contact_id=world.contact.id,
        type=ContactPointType.EMAIL,
        value=f"other-{uuid.uuid4().hex[:8]}@example.com",
    )
    db_session.add(other)
    db_session.flush()

    world.edit(db_session, recipient_contact_point_id=other.id)
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)
    assert "superseded" in str(invalidation_reason(db_session, approval, now=NOW))


def test_a_changed_subject_invalidates_the_approval(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    world.edit(db_session, subject="SYNTHETIC different subject")
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)


def test_a_changed_body_invalidates_the_approval(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    world.edit(db_session, body="SYNTHETIC different body")
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)


def test_a_changed_personalization_fact_invalidates_the_approval(
    db_session: Session, world: World
) -> None:
    """A different evidence citation is a different personalization claim (§8.4)."""
    approval = approved_approval(db_session, world)

    world.edit(db_session, evidence_ids=[uuid.uuid4()])
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)


def test_a_changed_product_status_invalidates_the_approval(
    db_session: Session, world: World
) -> None:
    approval = approved_approval(db_session, world)

    # The pinned status stops being effective — exactly what a new readiness version does.
    world.status.expires_or_review_by = NOW + timedelta(hours=1)
    db_session.flush()

    assert is_valid(db_session, approval, now=NOW)
    assert not is_valid(db_session, approval, now=NOW + timedelta(hours=2))
    assert "product status" in str(
        invalidation_reason(db_session, approval, now=NOW + timedelta(hours=2))
    )


def test_a_changed_claim_version_invalidates_the_approval(
    db_session: Session, world: World
) -> None:
    approval = approved_approval(db_session, world)

    world.claim_set.superseded_at = NOW
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)
    assert "claim set" in str(invalidation_reason(db_session, approval, now=NOW))


def test_an_unchanged_world_leaves_the_approval_valid(db_session: Session, world: World) -> None:
    """The counter-case: none of the six triggers fired, so it still authorizes."""
    approval = approved_approval(db_session, world)

    assert is_valid(db_session, approval, now=NOW)
    assert invalidation_reason(db_session, approval, now=NOW) is None
    require_valid(db_session, approval, now=NOW)  # must not raise


def test_require_valid_raises_rather_than_returning_false(
    db_session: Session, world: World
) -> None:
    """A caller that forgets to check a boolean must not be able to send (§11.4)."""
    approval = approved_approval(db_session, world)
    world.edit(db_session, body="SYNTHETIC edited")
    db_session.flush()

    with pytest.raises(ApprovalNotValid) as exc:
        require_valid(db_session, approval, now=NOW)

    assert "§8.4" in str(exc.value)


# --- expiry, revocation, and no return (criterion 3) ------------------------------------------


def test_an_expired_approval_authorizes_nothing(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    assert not is_valid(db_session, approval, now=NOW + DEFAULT_APPROVAL_TTL)
    assert "expired" in str(
        invalidation_reason(db_session, approval, now=NOW + DEFAULT_APPROVAL_TTL)
    )


def test_the_default_window_is_conservative() -> None:
    """`Q-020` has not set review thresholds, so the default is short by design."""
    assert timedelta(days=7) >= DEFAULT_APPROVAL_TTL


def test_a_revoked_approval_cannot_return_to_approved(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)
    revoke(db_session, approval, actor=OPERATOR, reason="operator withdrew it", now=NOW)

    with pytest.raises(IllegalTransition):
        approve(db_session, approval, actor=OPERATOR, now=NOW)


def test_an_expired_approval_cannot_return_to_approved(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)
    expire(db_session, approval, actor=OPERATOR, now=NOW)

    with pytest.raises(IllegalTransition):
        approve(db_session, approval, actor=OPERATOR, now=NOW)


def test_a_rejected_approval_cannot_return_to_approved(db_session: Session, world: World) -> None:
    approval = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    reject(db_session, approval, actor=OPERATOR, reason="not a fit", now=NOW)

    with pytest.raises(IllegalTransition):
        approve(db_session, approval, actor=OPERATOR, now=NOW)


def test_a_closed_approval_records_when_and_why(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    revoke(db_session, approval, actor=OPERATOR, reason="claim withdrawn", now=NOW)
    db_session.flush()

    assert approval.closed_at == NOW
    assert approval.closed_reason == "claim withdrawn"


def test_a_pending_approval_authorizes_nothing(db_session: Session, world: World) -> None:
    approval = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)


# --- audit ---------------------------------------------------------------------------------------


def test_the_decision_is_audited(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    events = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="approval", entity_id=str(approval.id))
        .order_by(AuditEvent.occurred_at)
        .all()
    )

    assert [e.action for e in events] == ["approval.requested", "approval.transitioned"]
    assert events[0].payload["content_hash"] == world.revision.content_hash
    assert (events[1].from_state, events[1].to_state) == ("pending", "approved")


def test_revocation_is_audited_with_its_reason(db_session: Session, world: World) -> None:
    approval = approved_approval(db_session, world)

    revoke(db_session, approval, actor=OPERATOR, reason="product paused", now=NOW)
    db_session.flush()

    event = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="approval", entity_id=str(approval.id))
        .order_by(AuditEvent.occurred_at.desc())
        .first()
    )

    assert event is not None
    assert event.to_state == "revoked"
    assert event.payload["reason"] == "product paused"


# --- T-137: the revocation entry point enforces its own rules ------------------------------------
#
# Most of this task already existed when it was reached: `T-021` gave `revoke()` its transition,
# actor, reason, and audit event, and `T-068a` gave it an endpoint and proved a revoked approval
# cannot dispatch. What did not exist is either rule holding at the *function*. The reason was
# required by a Pydantic model, so it was true of one caller rather than of the entity; and
# revoking twice arrived as `IllegalTransition`, which reads as a defect rather than as an answer.
#
# Both tests below call `revoke()` directly for exactly that reason — routing them through the
# endpoint would prove the schema works, which was never in doubt.


def test_a_revocation_without_a_reason_is_refused(db_session: Session, world: World) -> None:
    """Criterion 2 at the entry point. §17.6's operational actions are explicable."""
    approval = approved_approval(db_session, world)

    with pytest.raises(RevocationNeedsReason):
        revoke(db_session, approval, actor=OPERATOR, reason="", now=NOW)

    assert approval.state is ApprovalState.APPROVED


@pytest.mark.parametrize("blank", ["", " ", "\t", "\n  \n"])
def test_a_whitespace_only_reason_is_not_a_reason(
    db_session: Session, world: World, blank: str
) -> None:
    """Every shape of blank, not just the empty string: a space satisfies a `min_length=1` schema
    and records a revocation nobody can explain."""
    approval = approved_approval(db_session, world)

    with pytest.raises(RevocationNeedsReason):
        revoke(db_session, approval, actor=OPERATOR, reason=blank, now=NOW)


def test_a_refused_revocation_writes_no_audit_event(db_session: Session, world: World) -> None:
    """Refused before anything is written: an audit trail that recorded the attempt as a
    revocation would be worse than none, and the transition never happened."""
    approval = approved_approval(db_session, world)
    before = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="approval", entity_id=str(approval.id))
        .count()
    )

    with pytest.raises(RevocationNeedsReason):
        revoke(db_session, approval, actor=OPERATOR, reason="   ", now=NOW)

    assert (
        db_session.query(AuditEvent)
        .filter_by(entity_type="approval", entity_id=str(approval.id))
        .count()
        == before
    )


@pytest.mark.parametrize("closer", ["revoke", "expire"])
def test_revoking_an_already_closed_approval_is_a_domain_refusal(
    db_session: Session, world: World, closer: str
) -> None:
    """Criterion 3. Refused rather than silently ignored, and refused as an *approval* error:
    an operator double-clicking Revoke has done nothing wrong, and the answer they need is which
    terminal state it is already in."""
    approval = approved_approval(db_session, world)
    if closer == "revoke":
        revoke(db_session, approval, actor=OPERATOR, reason="operator withdrew it", now=NOW)
    else:
        expire(db_session, approval, actor=OPERATOR, now=NOW)
    db_session.flush()

    with pytest.raises(ApprovalAlreadyClosed, match=approval.state.value):
        revoke(db_session, approval, actor=OPERATOR, reason="again", now=NOW)


def test_the_closed_refusal_is_not_a_lifecycle_error(db_session: Session, world: World) -> None:
    """The distinction this task exists to draw, asserted rather than described: `ApprovalError`
    is what the endpoint maps to `409`, and `IllegalTransition` is what it used to arrive as."""
    approval = approved_approval(db_session, world)
    revoke(db_session, approval, actor=OPERATOR, reason="operator withdrew it", now=NOW)
    db_session.flush()

    with pytest.raises(ApprovalError) as refusal:
        revoke(db_session, approval, actor=OPERATOR, reason="again", now=NOW)

    assert not isinstance(refusal.value, IllegalTransition)


def test_revoking_a_never_approved_approval_stays_a_lifecycle_refusal(
    db_session: Session, world: World
) -> None:
    """Deliberately *not* absorbed into `ApprovalAlreadyClosed`. §8.2 has no
    `pending -> revoked` edge, so revoking something nobody approved is the lifecycle table's
    refusal to give — a different mistake from revoking something twice, and one the endpoint
    still maps to `409` through its `LifecycleError` arm."""
    approval = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )

    with pytest.raises(IllegalTransition):
        revoke(db_session, approval, actor=OPERATOR, reason="never mind", now=NOW)


def test_a_revoked_approval_authorizes_nothing(db_session: Session, world: World) -> None:
    """Criterion 1, restated at this entry point. `T-068a` proved it end to end from the endpoint
    (`tests/test_approval_lifecycle.py::test_a_revoked_approval_cannot_dispatch`); this is the
    same guarantee where `revoke()` itself can see it."""
    approval = approved_approval(db_session, world)

    revoke(db_session, approval, actor=OPERATOR, reason="product paused", now=NOW)
    db_session.flush()

    assert not is_valid(db_session, approval, now=NOW)
    with pytest.raises(ApprovalNotValid, match="revoked"):
        require_valid(db_session, approval, now=NOW)


def test_an_approval_pinning_nothing_is_not_valid(db_session: Session, world: World) -> None:
    """The reverse of what this asserted, and the reason ADR-029 exists.

    It was `test_approvals_with_no_product_claim_pin_nothing`, reading *"a message making no
    product statement has no product status to invalidate it"*, and it asserted the approval was
    **valid**. §11.4 says every external action contains `product_status_version` and
    `approved_claim_set_version` and lists both among the dispatch rechecks; an approval carrying
    neither cannot be shown to be current, so it does not authorize a send.
    """
    approval = request_approval(
        db_session, revision=world.revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    approve(db_session, approval, actor=OPERATOR, now=NOW)
    db_session.flush()

    assert approval.product_status_version_id is None
    assert approval.approved_claim_set_id is None
    assert not is_valid(db_session, approval, now=NOW)
