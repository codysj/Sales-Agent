"""Editing creates a new immutable revision (T-065a; §10.5, §12.3, §8.2, §8.4).

Three things the acceptance criteria name, and one the task's own design pulled in:

* **Editing an approved revision retires that approval.** An approval names an exact revision
  (ADR-008); approving text and then editing it is the failure §10.5's immutability rule exists
  to prevent. The retirement must land in the same transaction that makes the text obsolete.
* **The prior revision is byte-identical afterwards.** Asserted field by field rather than by
  comparing objects — an ORM identity check would pass while the columns had changed underneath.
* **Validation re-runs and can block.** Whatever passed for revision N proves nothing about N+1.
* **A mutation refuses cookie authentication.** This is the repository's first state-changing
  route, and a CSRF attack rides on a cookie the browser attaches by itself. `T-070` adds real
  protection; until then the exposure is removed rather than accepted, and that is worth a test
  because it is easy to relax by accident.
"""

import pathlib
import re
import uuid
from collections.abc import Iterator

import pytest
import structlog
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import create_candidate, transition
from app.campaigns.models import Campaign
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import publish_policy_version
from app.core.lifecycles import ApprovalState, CampaignCandidateState, MessageRevisionState
from app.core.security import CSRF_HEADER
from app.db.session import dispose_engines
from app.drafts_and_approvals import revisions
from app.drafts_and_approvals.approval import Approval, approve, request_approval
from app.drafts_and_approvals.editing import EditRefused, edit_revision
from app.drafts_and_approvals.models import MessageDraft, MessageRevision
from app.drafts_and_approvals.validation import Check
from app.identity.dependencies import SESSION_COOKIE
from app.identity.dependencies import db_session as db_session_dependency
from app.identity.models import Role, RoleKey, User, UserRole
from app.identity.sessions import issue_session
from app.main import create_app
from app.products_and_claims.models import Product
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from tests.factories import APPROVER, NOW

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-review-edit-test")


class World:
    """One candidate in review with one draft revision."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
        session.add(self.product)
        session.flush()
        self.campaign = Campaign(
            slug=f"synthetic-{uuid.uuid4().hex[:8]}",
            name="SYNTHETIC-Campaign",
            product_id=self.product.id,
            paused=False,
        )
        self.account = Account(
            domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account"
        )
        session.add_all([self.campaign, self.account])
        session.flush()
        # `T-055`'s validation reads the campaign policy, and a campaign with no approved rules
        # cannot produce an answer at all (§10.1). Published here so an edit fails validation for
        # a reason the test chose rather than for a missing fixture.
        publish_policy_version(
            session,
            campaign_id=self.campaign.id,
            policy=CampaignPolicy(),
            approved_by=APPROVER,
            approved_at=NOW,
        )
        self.contact = Contact(account_id=self.account.id, full_name="SYNTHETIC Person")
        session.add(self.contact)
        session.flush()
        self.recipient = ContactPoint(
            contact_id=self.contact.id,
            type=ContactPointType.EMAIL,
            value=f"{uuid.uuid4().hex[:8]}@{self.account.domain}",
            verification_state=VerificationState.VERIFIED,
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
        for step in (
            CampaignCandidateState.ELIGIBLE,
            CampaignCandidateState.RESEARCH_PENDING,
            CampaignCandidateState.RESEARCHED,
            CampaignCandidateState.REVIEW_PENDING,
        ):
            transition(session, self.candidate, step, actor=OPERATOR, reason="SYNTHETIC")

        self.draft = MessageDraft(candidate_id=self.candidate.id)
        session.add(self.draft)
        session.flush()
        self.revision = revisions.create_revision(
            session,
            draft=self.draft,
            recipient_contact_point_id=self.recipient.id,
            subject="SYNTHETIC original subject",
            body="SYNTHETIC original body.",
            created_by="drafting-task",
            actor=OPERATOR,
        )


@pytest.fixture
def world(db_session: Session) -> World:
    return World(db_session)


def snapshot(revision: MessageRevision) -> dict[str, object]:
    """Every field that would have to stay put for "byte-identical" to be true."""
    return {
        "subject": revision.subject,
        "body": revision.body,
        "content_hash": revision.content_hash,
        "revision_number": revision.revision_number,
        "recipient": revision.recipient_contact_point_id,
        "claims": list(revision.approved_claim_ids),
        "evidence": list(revision.evidence_ids),
    }


def approve_revision(
    session: Session, revision: MessageRevision, *, decided: bool = True
) -> Approval:
    """An approval bound to ``revision``, through the real approval path.

    ``pending`` leaves it awaiting a decision; ``approved`` decides it. Both matter here: §8.2
    allows `approved -> revoked` but not `pending -> revoked`, so an edit has to retire each one
    by the edge that exists for it.
    """
    approval = request_approval(
        session, revision=revision, approver_id=APPROVER, actor=OPERATOR, now=NOW
    )
    if decided:
        approve(session, approval, actor=OPERATOR, now=NOW)
    return approval


# --- criterion 1: editing an approved revision retires the approval ------------------------------


def test_editing_an_approved_revision_revokes_its_approval(
    db_session: Session, world: World
) -> None:
    """ADR-008 binds an approval to an exact revision. Editing the text must stop the approval
    being usable in the same transaction that makes it obsolete."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    revisions.transition(db_session, world.revision, MessageRevisionState.APPROVED, actor=OPERATOR)
    approval = approve_revision(db_session, world.revision)

    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    db_session.refresh(approval)
    assert approval.state is ApprovalState.REVOKED
    assert result.revoked_approvals == [approval.id]


def test_editing_expires_a_pending_approval_rather_than_revoking_it(
    db_session: Session, world: World
) -> None:
    """§8.2 allows `approved -> revoked` but not `pending -> revoked`. Expiring is the edge that
    exists, and it is the same outcome for a reviewer: no longer actionable."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    approval = approve_revision(db_session, world.revision, decided=False)

    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Timing",
        actor=OPERATOR,
    )

    db_session.refresh(approval)
    assert approval.state is ApprovalState.EXPIRED
    assert result.expired_approvals == [approval.id]


def test_an_edit_with_no_approval_retires_nothing(db_session: Session, world: World) -> None:
    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    assert result.revoked_approvals == []
    assert result.expired_approvals == []


# --- criterion 2: the prior revision is byte-identical -------------------------------------------


def test_the_prior_revision_is_unchanged_field_by_field(db_session: Session, world: World) -> None:
    """Asserted field by field, not by comparing objects: an ORM identity check would pass while
    the columns had changed underneath. This is the guarantee an auditor needs — the text someone
    approved is still readable exactly as they approved it."""
    before = snapshot(world.revision)

    edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Evidence does not support the claim",
        actor=OPERATOR,
    )

    db_session.refresh(world.revision)
    assert snapshot(world.revision) == before


def test_the_prior_revision_is_superseded(db_session: Session, world: World) -> None:
    edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    db_session.refresh(world.revision)
    assert world.revision.state is MessageRevisionState.SUPERSEDED


def test_the_edit_creates_revision_two(db_session: Session, world: World) -> None:
    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    assert result.revision.revision_number == 2
    assert result.revision.subject == "SYNTHETIC edited subject"
    assert result.superseded_revision_id == world.revision.id
    assert db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == 2


def test_the_new_revision_has_its_own_content_hash(db_session: Session, world: World) -> None:
    """Different text, different hash — otherwise the hash would not detect the change it exists
    to detect (§10.5)."""
    original_hash = world.revision.content_hash

    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    assert result.revision.content_hash != original_hash


def test_citations_carry_over_unless_changed(db_session: Session, world: World) -> None:
    """An edit is usually wording. Silently dropping the claim a sentence rests on would make the
    new revision fail `T-055`'s grounding check for a reason the reviewer never chose."""
    claim_id = uuid.uuid4()
    evidence_id = uuid.uuid4()
    # Set at creation. Assigning to an existing revision is refused by the database trigger — the
    # very immutability this task implements — so the fixture cannot take that shortcut either.
    cited = revisions.create_revision(
        db_session,
        draft=world.draft,
        recipient_contact_point_id=world.recipient.id,
        subject="SYNTHETIC cited subject",
        body="SYNTHETIC cited body.",
        approved_claim_ids=[claim_id],
        evidence_ids=[evidence_id],
        created_by="drafting-task",
        actor=OPERATOR,
    )

    result = edit_revision(
        db_session,
        cited,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    assert result.revision.approved_claim_ids == [claim_id]
    assert result.revision.evidence_ids == [evidence_id]


# --- criterion 3: validation re-runs, and can block -----------------------------------------------


def test_validation_reruns_on_the_new_revision(db_session: Session, world: World) -> None:
    """Whatever passed for revision N proves nothing about N+1."""
    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    assert result.revision.state in {
        MessageRevisionState.REVIEW_PENDING,
        MessageRevisionState.VALIDATION_FAILED,
    }


def test_validation_can_block_the_edit(db_session: Session, world: World) -> None:
    """Criterion 3's other direction. Citing a claim that does not exist fails `T-055`'s
    claim-citation check, and the revision lands in `validation_failed` — saved, so the reviewer
    can see what they wrote and why it was refused, rather than silently discarded."""
    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Evidence does not support the claim",
        actor=OPERATOR,
        approved_claim_ids=[uuid.uuid4()],
    )

    assert result.is_valid is False
    assert result.revision.state is MessageRevisionState.VALIDATION_FAILED
    assert result.validation.failures


def test_a_blocked_edit_still_retires_the_old_approval(db_session: Session, world: World) -> None:
    """The dangerous combination: an edit that fails validation must not leave the *old*
    approval live, or a reviewer would have obsolete text still approved."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    revisions.transition(db_session, world.revision, MessageRevisionState.APPROVED, actor=OPERATOR)
    approval = approve_revision(db_session, world.revision)

    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Evidence does not support the claim",
        actor=OPERATOR,
        approved_claim_ids=[uuid.uuid4()],
    )

    db_session.refresh(approval)
    assert result.is_valid is False
    assert approval.state is ApprovalState.REVOKED


# --- refusals -------------------------------------------------------------------------------------


def test_an_edit_needs_a_correction_reason(db_session: Session, world: World) -> None:
    """§12.3 item 7. A change nobody can explain later is a change nobody can review."""
    with pytest.raises(EditRefused, match="correction reason"):
        edit_revision(
            db_session,
            world.revision,
            subject="SYNTHETIC edited subject",
            body="SYNTHETIC edited body.",
            correction_reason="   ",
            actor=OPERATOR,
        )


def test_a_refused_edit_changes_nothing(db_session: Session, world: World) -> None:
    before = snapshot(world.revision)

    with pytest.raises(EditRefused):
        edit_revision(
            db_session,
            world.revision,
            subject="SYNTHETIC edited subject",
            body="SYNTHETIC edited body.",
            correction_reason="",
            actor=OPERATOR,
        )

    assert snapshot(world.revision) == before
    assert db_session.execute(select(func.count()).select_from(MessageRevision)).scalar_one() == 1


def test_a_superseded_revision_cannot_be_edited(db_session: Session, world: World) -> None:
    """Editing history would branch the chain, and §10.5's numbering assumes one line."""
    edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC edited subject",
        body="SYNTHETIC edited body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    with pytest.raises(EditRefused, match="branch"):
        edit_revision(
            db_session,
            world.revision,
            subject="SYNTHETIC second edit",
            body="SYNTHETIC second body.",
            correction_reason="Tone or wording",
            actor=OPERATOR,
        )


# --- editing is the way back from a refusal (T-211) ----------------------------------------------
#
# `T-208` let a reviewer refuse wording. `invalidated` was not editable, so that left the candidate
# with no legal move anywhere: it is already `approved`, and §8.2 gives an approved candidate one
# edge, to `invalidated`. Editing is the route back, and these two tests are the pair that makes it
# safe — the state is permitted, and only for the draft's last revision.


def test_a_refused_revision_can_be_edited_into_a_replacement(
    db_session: Session, world: World
) -> None:
    revisions.transition(
        db_session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    revisions.refuse(
        db_session, world.revision, reason="tone_or_positioning_problem", actor=OPERATOR
    )

    result = edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC replacement subject",
        body="SYNTHETIC replacement body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    assert result.revision.revision_number == 2
    # The refusal is history and stays exactly as it was recorded: still invalidated, still
    # carrying the reason. A replacement does not un-refuse what somebody refused.
    db_session.refresh(world.revision)
    assert world.revision.state is MessageRevisionState.INVALIDATED
    assert world.revision.refusal_reason == "tone_or_positioning_problem"


def test_a_refused_revision_that_is_no_longer_the_latest_cannot_be_edited(
    db_session: Session, world: World
) -> None:
    """The control on the state above, and the reason the check is about the draft rather than the
    revision: nothing supersedes an invalidated revision, so a draft can hold one *and* a later
    live one. Editing the older would base new text on refused wording and retire the current."""
    revisions.transition(
        db_session, world.revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR
    )
    revisions.refuse(
        db_session, world.revision, reason="tone_or_positioning_problem", actor=OPERATOR
    )
    edit_revision(
        db_session,
        world.revision,
        subject="SYNTHETIC replacement subject",
        body="SYNTHETIC replacement body.",
        correction_reason="Tone or wording",
        actor=OPERATOR,
    )

    with pytest.raises(EditRefused, match="not the latest revision"):
        edit_revision(
            db_session,
            world.revision,
            subject="SYNTHETIC third subject",
            body="SYNTHETIC third body.",
            correction_reason="Tone or wording",
            actor=OPERATOR,
        )


# --- the endpoint, and the first mutating route --------------------------------------------------


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """The app, reading the test's own transaction.

    Imported as `db_session_dependency` because the pytest fixture is also called `db_session`,
    and overriding one with the other is a mistake that reads as correct.
    """
    app = create_app(configure_logs=False)
    app.dependency_overrides[db_session_dependency] = lambda: db_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    dispose_engines()


def sign_in(session: Session, *roles: RoleKey) -> str:
    user = User(
        email=f"synthetic.{uuid.uuid4().hex[:8]}@example.com", display_name="SYNTHETIC Reviewer"
    )
    session.add(user)
    session.flush()
    for role in roles:
        row = session.execute(select(Role).where(Role.key == role.value)).scalar_one()
        session.add(UserRole(user_id=user.id, role_id=row.id, granted_by="operator-1"))
    session.flush()
    return issue_session(session, user, issued_via="test").token


def edit_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "subject": "SYNTHETIC edited subject",
        "body": "SYNTHETIC edited body.",
        "correction_reason": "Tone or wording",
    }
    payload.update(overrides)
    return payload


def test_a_cookie_cannot_authenticate_a_mutation(
    client: TestClient, db_session: Session, world: World
) -> None:
    """A CSRF attack works because a browser attaches a cookie by itself. `T-070a` made that
    survivable — a cookie caller now passes by echoing the CSRF token — and this is the test that
    stops the *bare* cookie being accepted by accident."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)
    client.cookies.set(SESSION_COOKIE, token)

    response = client.post(f"/api/review/revisions/{world.revision.id}/edit", json=edit_payload())

    # `403`, not `401`, since `T-070a`: the caller *is* authenticated, and the missing thing
    # is the CSRF token. Telling them to sign in again would send them round a loop that
    # cannot fix it. The property this test protects is unchanged — a cookie alone still
    # cannot mutate anything.
    assert response.status_code == 403
    assert CSRF_HEADER in response.json()["detail"].lower()


def test_a_bearer_token_can(client: TestClient, db_session: Session, world: World) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = client.post(
        f"/api/review/revisions/{world.revision.id}/edit",
        json=edit_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["revision"]["revision_number"] == 2


def test_a_role_without_the_permission_is_forbidden(
    client: TestClient, db_session: Session, world: World
) -> None:
    """`VIEWER` may read the queue and must not correct anything (§12.1)."""
    token = sign_in(db_session, RoleKey.VIEWER)

    response = client.post(
        f"/api/review/revisions/{world.revision.id}/edit",
        json=edit_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_an_unknown_revision_is_404(client: TestClient, db_session: Session, world: World) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = client.post(
        f"/api/review/revisions/{uuid.uuid4()}/edit",
        json=edit_payload(),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_a_stale_record_version_is_refused(
    client: TestClient, db_session: Session, world: World
) -> None:
    """Optimistic concurrency. Editing text nobody read is how two reviewers overwrite each
    other and neither finds out."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = client.post(
        f"/api/review/revisions/{world.revision.id}/edit",
        json=edit_payload(record_version="2020-01-01T00:00:00Z"),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 409


def test_a_missing_correction_reason_is_refused_by_the_schema(
    client: TestClient, db_session: Session, world: World
) -> None:
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = client.post(
        f"/api/review/revisions/{world.revision.id}/edit",
        json={"subject": "SYNTHETIC", "body": "SYNTHETIC"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 422


def test_the_response_reports_a_blocked_edit_with_its_checks(
    client: TestClient, db_session: Session, world: World
) -> None:
    """`is_valid: false` means saved *and* refused — the reviewer needs to see which check."""
    token = sign_in(db_session, RoleKey.OPERATOR_REVIEWER)

    response = client.post(
        f"/api/review/revisions/{world.revision.id}/edit",
        json=edit_payload(approved_claim_ids=[str(uuid.uuid4())]),
        headers={"Authorization": f"Bearer {token}"},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["is_valid"] is False
    assert body["failed_checks"]


def test_the_actor_comes_from_the_session_not_the_body(
    client: TestClient, db_session: Session, world: World
) -> None:
    """§12.2's immutable attribution: a body field naming the actor would be attribution the
    caller chose for themselves."""
    from app.drafts_and_approvals.api import EditRequest

    assert "actor" not in EditRequest.model_fields
    assert "approver_id" not in EditRequest.model_fields


# --- the reviewer-facing explanation of each check -----------------------------------------------


def test_every_validation_check_has_a_reviewer_explanation() -> None:
    """`T-065b`'s form explains each failed check in a sentence a reviewer can act on.

    Asserted from here because this is the only place both facts exist: `Check` is defined in
    Python and the explanations live in TypeScript. A check added on this side and forgotten on
    that one would reach a reviewer as a bare identifier — technically honest, practically
    useless — and nothing else in either suite would notice.
    """
    form = (
        pathlib.Path(__file__).resolve().parents[2] / "frontend" / "app" / "review" / "EditForm.tsx"
    ).read_text(encoding="utf-8")
    explained = set(re.findall(r"^  ([a-z_]+):", form, flags=re.MULTILINE))

    missing = {check.value for check in Check} - explained
    assert not missing, (
        f"these validation checks have no reviewer-facing explanation in EditForm.tsx: "
        f"{sorted(missing)}"
    )
