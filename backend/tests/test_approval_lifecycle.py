"""What happens to an approval after it is granted (T-068a; §7.5, §8.4, §17.6, §11.4).

§8.4 lists six changes that invalidate an approval, and `T-021` already checked all of them. What
it answered with was **prose**: "approved claim set has been superseded" tells a reviewer the
category of problem and nothing they can act on. §7.5 asks the application to *flag* stale
approvals, and a flag nobody can trace back to a version starts an investigation rather than
ending one. So the first block below walks every trigger and asserts the identifier, one at a time
— a table-driven test over a subset would pass with the interesting triggers missing.

The other three blocks are about consequences: revocation needs the same authority that granted
the approval, it has to leave an audit trail, and neither a revoked nor an invalidated approval
may reach a dispatch. That last one is asserted at the **precondition** rather than at a caller,
because a guarantee that holds only for callers who remember to ask is not a guarantee.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import transition
from app.core.lifecycles import ApprovalState, CampaignCandidateState, MessageRevisionState
from app.db.session import dispose_engines
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.approval import (
    Approval,
    ApprovalNotValid,
    InvalidationTrigger,
    approvals_needing_attention,
    approve,
    invalidation_detail,
    invalidation_reason,
    request_approval,
    require_valid,
    revoke,
)
from app.identity.dependencies import SESSION_COOKIE, db_session
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.sessions import issue_session
from app.main import create_app
from app.outreach_and_replies.approve_message import approve_message
from app.products_and_claims.claim_models import ApprovedClaimSet
from tests.factories import APPROVER, NOW
from tests.test_revision_validation import World as ValidWorld

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-approval-lifecycle-test")


class World(ValidWorld):
    """A validated revision in review, approved — the state this task is about."""

    def __init__(self, session: Session) -> None:
        super().__init__(session)
        for step in (
            CampaignCandidateState.RESEARCH_PENDING,
            CampaignCandidateState.RESEARCHED,
            CampaignCandidateState.REVIEW_PENDING,
        ):
            transition(session, self.candidate, step, actor=OPERATOR, reason="SYNTHETIC")
        revisions.transition(
            session, self.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
        )
        # `T-157`: the transaction refuses to grant an approval that pins no claim set.
        self.claim_set = self.publish_current_claim_set()
        outcome = approve_message(
            session,
            self.revision,
            recipient=self.recipient,
            approver_id=APPROVER,
            actor=OPERATOR,
        )
        self.approval = outcome.approval

    def a_claim_set(self, *, superseded: bool = False) -> ApprovedClaimSet:
        """A real claim set, because the pin is a foreign key.

        `approved_claim_set_id` references `approved_claim_set`, so a random UUID cannot stand in
        for one — the insert is refused before any invalidation logic runs. Superseding it is the
        real mechanism `T-056` uses.

        Inserted directly rather than through `publish_claim_set`, and at the next free version:
        publishing would supersede the world's current set, and since `T-157` that set is the one
        `self.approval` pins — so every test here would start with an already-invalid approval.
        """
        claim_set = ApprovedClaimSet(
            product_id=self.product.id,
            campaign_id=self.campaign.id,
            version=self._next_claim_set_version(),
            approved_by=APPROVER,
            approved_at=NOW - timedelta(days=2),
            superseded_at=(NOW - timedelta(days=1)) if superseded else None,
        )
        self.session.add(claim_set)
        self.session.flush()
        return claim_set

    def _next_claim_set_version(self) -> int:
        """The next free version for this product and campaign.

        `uq_approved_claim_set_scope_version` is the real arbiter; this only keeps the fixture
        from colliding with the set published in `__init__`.
        """
        highest = self.session.execute(
            select(func.max(ApprovedClaimSet.version)).where(
                ApprovedClaimSet.product_id == self.product.id,
                ApprovedClaimSet.campaign_id == self.campaign.id,
            )
        ).scalar_one()
        return int(highest or 0) + 1

    def pinned_approval(
        self,
        *,
        product_status_version_id: uuid.UUID | None = None,
        approved_claim_set_id: uuid.UUID | None = None,
    ) -> Approval:
        """An approval on a *fresh* revision, carrying the version pins listed in section 11.4.

        Needed because an approval's pins are immutable by database trigger
        (`approval_pins_immutable`) — correctly, since an approval that could be repointed at a
        different claim set would authorize something nobody approved. A test for the pin-related
        triggers therefore cannot mutate an existing approval; it has to create one that pins the
        value from the start.

        A fresh revision, because `uq_approval_live_per_revision` allows one live approval per
        revision — the same invariant seen from the other side.
        """
        revision = self.make_revision()
        revisions.transition(
            self.session, revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
        )
        # The pin the caller did not name is filled from this world's current one
        # (`T-193b`/ADR-029). A test naming one pin wants an approval that differs in
        # *that* pin; leaving the other null would make it invalid for a second reason and
        # the assertion would pass for the wrong one.
        approval = request_approval(
            self.session,
            revision=revision,
            approver_id=APPROVER,
            actor=OPERATOR,
            product_status_version_id=product_status_version_id or self.status.id,
            approved_claim_set_id=approved_claim_set_id or self.claim_set.id,
        )
        return approve(self.session, approval, actor=OPERATOR)


@pytest.fixture
def world(db_session_fixture: Session) -> World:
    return World(db_session_fixture)


@pytest.fixture
def db_session_fixture(db_session: Session) -> Session:
    return db_session


@pytest.fixture
def client(db_session_fixture: Session) -> Iterator[TestClient]:
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session] = lambda: db_session_fixture
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


def a_user(session: Session, role: RoleKey) -> User:
    user = User(
        email=f"synthetic.{uuid.uuid4().hex[:8]}@example.com",
        display_name="SYNTHETIC User",
        active=True,
    )
    session.add(user)
    session.flush()
    found = session.execute(select(Role).where(Role.key == role.value)).scalar_one()
    session.add(UserRole(user_id=user.id, role_id=found.id, granted_by="synthetic-admin"))
    session.flush()
    return user


@pytest.fixture
def approver_headers(db_session_fixture: Session) -> dict[str, str]:
    token = issue_session(
        db_session_fixture, a_user(db_session_fixture, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token
    return {"authorization": f"Bearer {token}"}


def revoke_url(world: World) -> str:
    return f"/api/review/approvals/{world.approval.id}/revoke"


# --- criterion 1: every trigger names the record that caused it
# ------------------------------------


def test_a_live_approval_has_no_invalidation(db_session: Session, world: World) -> None:
    """The baseline. Without it every assertion below could pass against a function that always
    reported a problem."""
    assert invalidation_detail(db_session, world.approval) is None
    assert invalidation_reason(db_session, world.approval) is None


def test_a_revoked_approval_reports_its_state(db_session: Session, world: World) -> None:
    # Through `revoke`, not by assigning the state: `ck_approval_closed_state_needs_a_timestamp`
    # makes `closed_at` part of what `revoked` *means*, so a test that set only the state would be
    # asserting about a row the schema forbids.
    revoke(db_session, world.approval, actor=OPERATOR, reason="SYNTHETIC")

    detail = invalidation_detail(db_session, world.approval)

    assert detail is not None
    assert detail.trigger is InvalidationTrigger.NOT_APPROVED
    assert "revoked" in detail.reason
    # No triggering id: this is a fact about the approval itself, not about another row.
    assert detail.triggering_id is None


def test_an_expired_approval_reports_when(db_session: Session, world: World) -> None:
    later = world.approval.approval_expires_at + timedelta(seconds=1)

    detail = invalidation_detail(db_session, world.approval, now=later)

    assert detail is not None
    assert detail.trigger is InvalidationTrigger.EXPIRED
    assert world.approval.approval_expires_at.isoformat() in detail.reason
    assert detail.triggering_id is None


def test_a_retired_revision_names_the_revision(db_session: Session, world: World) -> None:
    """§8.4: an edit invalidates the approval. `T-065a` supersedes the old revision, so this is
    the trigger a reviewer hits by correcting text they had already approved."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.SUPERSEDED, actor=OPERATOR
    )

    detail = invalidation_detail(db_session, world.approval)

    assert detail is not None
    assert detail.trigger is InvalidationTrigger.REVISION_RETIRED
    assert detail.triggering_id == world.revision.id


def test_the_approved_content_hash_cannot_be_repointed(db_session: Session, world: World) -> None:
    """§8.4's four content triggers all change the content hash, and the check for a
    mismatch cannot be reached by any legitimate path.

    Two immutabilities meet here: `T-020`'s trigger makes a revision's content unchangeable, and
    `approval_pins_immutable` makes the approval's copy of the hash unchangeable. The two can only
    disagree if one of those triggers has been removed. The check stays as the guard for that
    case, and this test records *why* it has no positive case rather than leaving a reader to
    conclude it went untested by oversight.
    """
    with pytest.raises(Exception, match="immutable"):
        db_session.execute(
            text("UPDATE approval SET approved_content_hash = :value WHERE id = :approval"),
            {"value": "0" * 64, "approval": world.approval.id},
        )
    db_session.rollback()


def test_the_approved_recipient_cannot_be_repointed(db_session: Session, world: World) -> None:
    """The `recipient_changed` trigger, and why it too has no positive case.

    An approval that could be repointed at a different address would authorize outreach nobody
    approved — ADR-008's exact recipient, held by the same trigger that pins the hash. The
    detection stays in `invalidation_detail` as the guard for a schema that lost it.
    """
    with pytest.raises(Exception, match="immutable"):
        db_session.execute(
            text("UPDATE approval SET recipient_contact_point_id = :value WHERE id = :approval"),
            {"value": str(uuid.uuid4()), "approval": world.approval.id},
        )
    db_session.rollback()


def test_a_superseded_product_status_names_the_version(db_session: Session, world: World) -> None:
    """§8.4 lists product status as a trigger, and `T-056` is what supersedes one.

    The pin is set at approval time and never after: `approval_pins_immutable` refuses an update,
    which is why this builds a pinned approval rather than mutating `world.approval`.
    """
    approval = world.pinned_approval(product_status_version_id=world.status.id)
    # Asked at a moment before the pinned version took effect, which is what
    # `is_effective_at` answers `False` to. The version is real — it is a foreign key — so the
    # only way to make it ineffective is to move the moment or to supersede it, and moving the
    # moment keeps this test about the trigger rather than about `T-056`.
    before_it_applied = world.status.effective_from - timedelta(seconds=1)

    detail = invalidation_detail(db_session, approval, now=before_it_applied)

    assert detail is not None
    assert detail.trigger is InvalidationTrigger.PRODUCT_STATUS_SUPERSEDED
    assert detail.triggering_id == world.status.id


def test_a_superseded_claim_set_names_the_set(db_session: Session, world: World) -> None:
    """The trigger that motivated this task: "approved claim set has been superseded" told a
    reviewer nothing they could look up."""
    claim_set = world.a_claim_set(superseded=True)
    approval = world.pinned_approval(approved_claim_set_id=claim_set.id)

    detail = invalidation_detail(db_session, approval)

    assert detail is not None
    assert detail.trigger is InvalidationTrigger.CLAIM_SET_SUPERSEDED
    assert detail.triggering_id == claim_set.id


def test_the_prose_form_still_answers_for_every_trigger(db_session: Session, world: World) -> None:
    """`invalidation_reason` is derived from the detail, not reimplemented — the dispatch path
    (§11.4) raises with it and must not have drifted from what the dashboard shows."""
    approval = world.pinned_approval(approved_claim_set_id=world.a_claim_set(superseded=True).id)

    detail = invalidation_detail(db_session, approval)
    reason = invalidation_reason(db_session, approval)

    assert detail is not None
    assert reason == detail.reason


# --- criterion 3: neither a revoked nor an invalidated approval can dispatch
# -----------------------


def test_a_revoked_approval_cannot_dispatch(db_session: Session, world: World) -> None:
    """Asserted at `require_valid`, which is what the dispatch transaction calls (§11.4) — not at
    a caller that might simply forget to ask."""
    # Through `revoke`, not by assigning the state: `ck_approval_closed_state_needs_a_timestamp`
    # makes `closed_at` part of what `revoked` *means*, so a test that set only the state would be
    # asserting about a row the schema forbids.
    revoke(db_session, world.approval, actor=OPERATOR, reason="SYNTHETIC")

    with pytest.raises(ApprovalNotValid, match="revoked"):
        require_valid(db_session, world.approval)


def test_an_invalidated_approval_cannot_dispatch(db_session: Session, world: World) -> None:
    """The §8.4 half: an approval still in `approved` whose claim set moved underneath it."""
    approval = world.pinned_approval(approved_claim_set_id=world.a_claim_set(superseded=True).id)

    with pytest.raises(ApprovalNotValid, match="claim set"):
        require_valid(db_session, approval)


def test_an_expired_approval_cannot_dispatch(db_session: Session, world: World) -> None:
    later = world.approval.approval_expires_at + timedelta(seconds=1)

    with pytest.raises(ApprovalNotValid, match="expired"):
        require_valid(db_session, world.approval, now=later)


def test_a_live_approval_still_dispatches(db_session: Session, world: World) -> None:
    """The other direction. A `require_valid` that refused everything would satisfy all three
    tests above and stop every send."""
    require_valid(db_session, world.approval)


# --- criterion 4: the attention list, in both directions
# -------------------------------------------


def test_a_live_approval_needs_no_attention(db_session: Session, world: World) -> None:
    assert approvals_needing_attention(db_session) == []


def test_an_invalidated_approval_appears_with_its_trigger(
    db_session: Session, world: World
) -> None:
    claim_set = world.a_claim_set(superseded=True)
    approval = world.pinned_approval(approved_claim_set_id=claim_set.id)

    found = {each.id: detail for each, detail in approvals_needing_attention(db_session)}

    # The world's first approval is in here too, and correctly: `pinned_approval` writes a new
    # revision, which supersedes the one that approval named. Asserting a single entry would have
    # been asserting that §8.4's edit trigger does *not* fire, which is the opposite of the truth.
    assert approval.id in found
    assert found[approval.id].trigger is InvalidationTrigger.CLAIM_SET_SUPERSEDED
    assert found[approval.id].triggering_id == claim_set.id


def test_a_revoked_approval_is_not_an_attention_item(db_session: Session, world: World) -> None:
    """Somebody dealt with it. Listing handled approvals would bury the ones nobody has looked
    at, which is the opposite of what §7.5's flag is for."""
    # Through `revoke`, not by assigning the state: `ck_approval_closed_state_needs_a_timestamp`
    # makes `closed_at` part of what `revoked` *means*, so a test that set only the state would be
    # asserting about a row the schema forbids.
    revoke(db_session, world.approval, actor=OPERATOR, reason="SYNTHETIC")

    assert approvals_needing_attention(db_session) == []


def test_an_expired_approval_is_an_attention_item(db_session: Session, world: World) -> None:
    """The case a state filter alone would miss: still `approved`, and stale."""
    later = world.approval.approval_expires_at + timedelta(seconds=1)

    found = approvals_needing_attention(db_session, now=later)

    assert [approval.id for approval, _ in found] == [world.approval.id]


def test_the_attention_endpoint_returns_the_triggering_id(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    claim_set = world.a_claim_set(superseded=True)
    approval = world.pinned_approval(approved_claim_set_id=claim_set.id)

    body = client.get("/api/review/attention/approvals", headers=approver_headers).json()

    row = next(item for item in body["items"] if item["approval_id"] == str(approval.id))
    assert row["trigger"] == "claim_set_superseded"
    assert row["triggering_id"] == str(claim_set.id)


def test_the_attention_endpoint_omits_live_approvals(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    body = client.get("/api/review/attention/approvals", headers=approver_headers).json()

    assert body["items"] == []


def test_the_attention_endpoint_needs_a_session(client: TestClient, world: World) -> None:
    assert client.get("/api/review/attention/approvals").status_code == 401


# --- criterion 2: revocation, its authority, and its audit event ----------------------------------


def test_revoking_moves_the_approval(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    response = client.post(
        revoke_url(world), json={"reason": "SYNTHETIC: the claim changed"}, headers=approver_headers
    )

    assert response.status_code == 200, response.text
    db_session.refresh(world.approval)
    assert world.approval.state is ApprovalState.REVOKED


def test_revoking_writes_an_audit_event_naming_the_actor(
    client: TestClient, db_session: Session, world: World, db_session_fixture: Session
) -> None:
    """§17.6. A revocation nobody can attribute is one a reviewer cannot distinguish from a
    fault."""
    user = a_user(db_session_fixture, RoleKey.OPERATOR_REVIEWER)
    token = issue_session(db_session_fixture, user, issued_via="test").token
    before = db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one()

    client.post(
        revoke_url(world),
        json={"reason": "SYNTHETIC: the claim changed"},
        headers={"authorization": f"Bearer {token}"},
    )

    # `entity_id` is a string column, so the comparison is against the string form — matching on
    # the UUID object asks PostgreSQL for an operator that does not exist.
    events = (
        db_session.execute(
            select(AuditEvent)
            .where(AuditEvent.entity_id == str(world.approval.id))
            .order_by(AuditEvent.occurred_at.desc())
        )
        .scalars()
        .all()
    )
    assert db_session.execute(select(func.count()).select_from(AuditEvent)).scalar_one() > before
    assert any(event.actor_id == str(user.id) for event in events), (
        f"no audit event attributed to the revoking user; saw {[e.actor_id for e in events]}"
    )


def test_a_reason_is_required(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    """No default: §17.6 wants operational actions explicable."""
    response = client.post(revoke_url(world), json={}, headers=approver_headers)

    assert response.status_code == 422


def test_a_blank_reason_is_refused(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    response = client.post(revoke_url(world), json={"reason": ""}, headers=approver_headers)

    assert response.status_code == 422


def test_a_role_without_the_permission_cannot_revoke(
    client: TestClient, db_session: Session, world: World, db_session_fixture: Session
) -> None:
    """The same permission that granted it: a role able to withdraw but not grant could stop any
    outreach it disliked."""
    token = issue_session(
        db_session_fixture,
        a_user(db_session_fixture, RoleKey.CAMPAIGN_SALES_OWNER),
        issued_via="test",
    ).token

    response = client.post(
        revoke_url(world),
        json={"reason": "SYNTHETIC"},
        headers={"authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    db_session.refresh(world.approval)
    assert world.approval.state is ApprovalState.APPROVED


def test_a_cookie_cannot_authenticate_a_revocation(
    client: TestClient, db_session: Session, world: World, db_session_fixture: Session
) -> None:
    token = issue_session(
        db_session_fixture, a_user(db_session_fixture, RoleKey.OPERATOR_REVIEWER), issued_via="test"
    ).token
    client.cookies.set(SESSION_COOKIE, token)

    response = client.post(revoke_url(world), json={"reason": "SYNTHETIC"}, headers={})

    # `403`, not `401`, since `T-070a`: the caller *is* authenticated, and the missing thing
    # is the CSRF token. Telling them to sign in again would send them round a loop that
    # cannot fix it. The property this test protects is unchanged — a cookie alone still
    # cannot mutate anything.
    assert response.status_code == 403
    db_session.refresh(world.approval)
    assert world.approval.state is ApprovalState.APPROVED


def test_a_stale_record_version_is_refused(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    response = client.post(
        revoke_url(world),
        json={"reason": "SYNTHETIC", "record_version": "2020-01-01T00:00:00Z"},
        headers=approver_headers,
    )

    assert response.status_code == 409
    db_session.refresh(world.approval)
    assert world.approval.state is ApprovalState.APPROVED


def test_an_unknown_approval_is_404(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    response = client.post(
        f"/api/review/approvals/{uuid.uuid4()}/revoke",
        json={"reason": "SYNTHETIC"},
        headers=approver_headers,
    )

    assert response.status_code == 404


def test_revoking_twice_is_refused(
    client: TestClient, world: World, approver_headers: dict[str, str]
) -> None:
    """§8.2 offers `approved -> revoked` and nothing out of `revoked`."""
    assert (
        client.post(
            revoke_url(world), json={"reason": "SYNTHETIC"}, headers=approver_headers
        ).status_code
        == 200
    )

    again = client.post(revoke_url(world), json={"reason": "SYNTHETIC"}, headers=approver_headers)

    assert again.status_code == 409


def test_a_revoked_approval_leaves_the_attention_list(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """The loop closes: an invalidated approval is flagged, revoking it is the response, and it
    stops being an attention item — which is what makes the list a queue rather than a log."""
    approval = world.pinned_approval(approved_claim_set_id=world.a_claim_set(superseded=True).id)
    assert approval.id in {each.id for each, _ in approvals_needing_attention(db_session)}

    client.post(
        f"/api/review/approvals/{approval.id}/revoke",
        json={"reason": "SYNTHETIC"},
        headers=approver_headers,
    )

    assert approval.id not in {each.id for each, _ in approvals_needing_attention(db_session)}


def test_a_revoked_approval_still_cannot_dispatch(
    client: TestClient, db_session: Session, world: World, approver_headers: dict[str, str]
) -> None:
    """End to end: revoked through the endpoint, refused at the precondition."""
    client.post(revoke_url(world), json={"reason": "SYNTHETIC"}, headers=approver_headers)
    db_session.refresh(world.approval)

    with pytest.raises(ApprovalNotValid):
        require_valid(db_session, world.approval, now=datetime.now(UTC))
