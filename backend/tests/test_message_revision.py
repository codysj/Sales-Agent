"""A revision means the same thing forever (T-020; §10.5, §8.4, §11.4).

An approval binds to one exact ``message_revision_id`` and the final send transaction rechecks
it. Everything here exists so that binding stays honest: content cannot be edited, editing
produces a new revision, and the hash notices any difference at all.
"""

import uuid

import pytest
import structlog
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.campaigns.candidate import CampaignCandidate, create_candidate
from app.campaigns.models import Campaign
from app.core.lifecycles import IllegalTransition, MessageRevisionState
from app.drafts_and_approvals.models import DraftPurpose, MessageDraft, MessageRevision
from app.drafts_and_approvals.revisions import (
    RevisionError,
    compute_content_hash,
    create_revision,
    latest_revision,
    live_revision,
    transition,
)
from app.products_and_claims.models import Product
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-revision-test")


@pytest.fixture
def recipient(db_session: Session) -> ContactPoint:
    account = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account")
    db_session.add(account)
    db_session.flush()
    contact = Contact(account_id=account.id, full_name="SYNTHETIC Person")
    db_session.add(contact)
    db_session.flush()
    point = ContactPoint(
        contact_id=contact.id,
        type=ContactPointType.EMAIL,
        value=f"{uuid.uuid4().hex[:8]}@example.com",
    )
    db_session.add(point)
    db_session.flush()
    return point


@pytest.fixture
def draft(db_session: Session, recipient: ContactPoint) -> MessageDraft:
    product = Product(slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Product")
    db_session.add(product)
    db_session.flush()
    campaign = Campaign(
        slug=f"synthetic-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Campaign", product_id=product.id
    )
    db_session.add(campaign)
    db_session.flush()
    contact = db_session.get(Contact, recipient.contact_id)
    assert contact is not None
    candidate: CampaignCandidate = create_candidate(
        db_session,
        campaign_id=campaign.id,
        account_id=contact.account_id,
        contact_id=contact.id,
        actor=OPERATOR,
    )
    item = MessageDraft(candidate_id=candidate.id)
    db_session.add(item)
    db_session.flush()
    return item


def add_revision(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint, **overrides: object
) -> MessageRevision:
    values: dict[str, object] = {
        "recipient_contact_point_id": recipient.id,
        "subject": "SYNTHETIC subject",
        "body": "SYNTHETIC body referencing a synthetic claim.",
        "approved_claim_ids": [],
        "evidence_ids": [],
        "created_by": "drafter-1",
    }
    values.update(overrides)
    return create_revision(db_session, draft=draft, actor=OPERATOR, **values)  # type: ignore[arg-type]


# --- content immutability (criterion 1) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("subject", "'tampered'"),
        ("body", "'tampered'"),
        ("content_hash", "repeat('a', 64)"),
        ("created_by", "'someone-else'"),
        ("revision_number", "99"),
    ],
)
def test_content_columns_cannot_be_updated(
    column: str, value: str, db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    revision = add_revision(db_session, draft, recipient)
    db_session.flush()

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text(f"UPDATE message_revision SET {column} = {value} WHERE id = :id"),
            {"id": revision.id},
        )

    assert "immutable" in str(exc.value)


def test_the_citation_arrays_cannot_be_updated(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    """Array columns, not join tables, precisely so this is one immutable row."""
    revision = add_revision(db_session, draft, recipient, approved_claim_ids=[uuid.uuid4()])
    db_session.flush()

    with pytest.raises(DBAPIError):
        db_session.execute(
            text(
                "UPDATE message_revision SET approved_claim_ids = ARRAY[gen_random_uuid()] "
                "WHERE id = :id"
            ),
            {"id": revision.id},
        )


def test_the_recipient_cannot_be_repointed(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    """§11.4 approves "this message to this person"; a new address is a new revision."""
    revision = add_revision(db_session, draft, recipient)
    db_session.flush()

    revision.recipient_contact_point_id = uuid.uuid4()

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_state_remains_mutable(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    """Progressing draft -> review_pending changes nothing about what the message says."""
    revision = add_revision(db_session, draft, recipient)

    transition(db_session, revision, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR)

    assert revision.state is MessageRevisionState.REVIEW_PENDING


# --- editing creates a successor (criterion 2) ----------------------------------------------------


def test_a_second_revision_supersedes_the_first(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    first = add_revision(db_session, draft, recipient, subject="SYNTHETIC first")

    second = add_revision(db_session, draft, recipient, subject="SYNTHETIC second")
    db_session.flush()

    assert first.state is MessageRevisionState.SUPERSEDED
    assert first.retired_at is not None
    assert second.revision_number == 2
    assert second.state is MessageRevisionState.DRAFT


def test_only_one_revision_is_live(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    add_revision(db_session, draft, recipient, subject="SYNTHETIC v1")
    add_revision(db_session, draft, recipient, subject="SYNTHETIC v2")
    third = add_revision(db_session, draft, recipient, subject="SYNTHETIC v3")
    db_session.flush()

    assert live_revision(db_session, draft.id) is not None
    assert live_revision(db_session, draft.id).id == third.id  # type: ignore[union-attr]
    assert latest_revision(db_session, draft.id).revision_number == 3  # type: ignore[union-attr]


def test_editing_an_approved_revision_supersedes_it(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    """§10.5: editing an approved message creates a new revision.

    T-021 will additionally invalidate the prior approval.
    """
    approved = add_revision(db_session, draft, recipient)
    transition(db_session, approved, MessageRevisionState.REVIEW_PENDING, actor=OPERATOR)
    transition(db_session, approved, MessageRevisionState.APPROVED, actor=OPERATOR)

    add_revision(db_session, draft, recipient, subject="SYNTHETIC edited")
    db_session.flush()

    assert approved.state is MessageRevisionState.SUPERSEDED


def test_a_superseded_revision_is_terminal(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    first = add_revision(db_session, draft, recipient)
    add_revision(db_session, draft, recipient, subject="SYNTHETIC next")

    with pytest.raises(IllegalTransition):
        transition(db_session, first, MessageRevisionState.APPROVED, actor=OPERATOR)


def test_revision_numbers_are_unique_per_draft(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    add_revision(db_session, draft, recipient)
    db_session.add(
        MessageRevision(
            draft_id=draft.id,
            revision_number=1,
            recipient_contact_point_id=recipient.id,
            subject="SYNTHETIC duplicate",
            body="SYNTHETIC body",
            approved_claim_ids=[],
            evidence_ids=[],
            content_hash="b" * 64,
            created_by="drafter-1",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- the content hash (criterion 3) ---------------------------------------------------------------


def _hash(**overrides: object) -> str:
    base: dict[str, object] = {
        "recipient_contact_point_id": uuid.UUID(int=1),
        "subject": "subject",
        "body": "body",
        "approved_claim_ids": [uuid.UUID(int=2)],
        "evidence_ids": [uuid.UUID(int=3)],
    }
    base.update(overrides)
    return compute_content_hash(**base)  # type: ignore[arg-type]


def test_the_hash_is_stable_for_identical_content() -> None:
    assert _hash() == _hash()


@pytest.mark.parametrize(
    ("field", "changed"),
    [
        ("recipient_contact_point_id", uuid.UUID(int=99)),
        ("subject", "different subject"),
        ("body", "different body"),
        ("approved_claim_ids", [uuid.UUID(int=99)]),
        ("evidence_ids", [uuid.UUID(int=99)]),
    ],
)
def test_any_change_alters_the_hash(field: str, changed: object) -> None:
    assert _hash(**{field: changed}) != _hash()


def test_adding_a_citation_alters_the_hash() -> None:
    assert _hash(approved_claim_ids=[uuid.UUID(int=2), uuid.UUID(int=4)]) != _hash()


def test_reordering_citations_alters_the_hash() -> None:
    """Order is preserved, not sorted: err toward invalidating an approval, not keeping it."""
    both = [uuid.UUID(int=2), uuid.UUID(int=4)]

    assert _hash(approved_claim_ids=both) != _hash(approved_claim_ids=list(reversed(both)))


def test_the_stored_hash_matches_the_stored_content(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    claims = [uuid.uuid4()]
    evidence = [uuid.uuid4(), uuid.uuid4()]
    revision = add_revision(
        db_session, draft, recipient, approved_claim_ids=claims, evidence_ids=evidence
    )
    db_session.flush()

    assert revision.content_hash == compute_content_hash(
        recipient_contact_point_id=recipient.id,
        subject=revision.subject,
        body=revision.body,
        approved_claim_ids=claims,
        evidence_ids=evidence,
    )


def test_a_malformed_hash_is_rejected(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    db_session.add(
        MessageRevision(
            draft_id=draft.id,
            revision_number=1,
            recipient_contact_point_id=recipient.id,
            subject="SYNTHETIC",
            body="SYNTHETIC",
            approved_claim_ids=[],
            evidence_ids=[],
            content_hash="not-a-hash",
            created_by="drafter-1",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- citations ------------------------------------------------------------------------------------


def test_duplicate_citations_are_rejected(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    duplicated = uuid.uuid4()

    with pytest.raises(RevisionError, match="duplicate claim"):
        add_revision(db_session, draft, recipient, approved_claim_ids=[duplicated, duplicated])


def test_a_revision_may_cite_nothing(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    """A message with no product sentence and no personalization is legal, if unusual."""
    revision = add_revision(db_session, draft, recipient)
    db_session.flush()

    assert revision.approved_claim_ids == []
    assert revision.evidence_ids == []


def test_citations_survive_a_round_trip(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    claims = [uuid.uuid4(), uuid.uuid4()]
    revision = add_revision(db_session, draft, recipient, approved_claim_ids=claims)
    db_session.flush()
    db_session.expire(revision)

    assert revision.approved_claim_ids == claims


# --- structure and audit --------------------------------------------------------------------------


def test_drafts_default_to_initial_outreach(draft: MessageDraft) -> None:
    """§8.4 governs follow-ups differently; the safe default is the one that gets approved."""
    assert draft.purpose is DraftPurpose.INITIAL_OUTREACH


def test_a_recipient_in_use_cannot_be_deleted(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    add_revision(db_session, draft, recipient)
    db_session.flush()

    db_session.delete(recipient)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_creation_and_supersession_are_audited(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    first = add_revision(db_session, draft, recipient)
    add_revision(db_session, draft, recipient, subject="SYNTHETIC second")
    db_session.flush()

    events = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="message_revision")
        .order_by(AuditEvent.occurred_at)
        .all()
    )
    actions = [e.action for e in events]

    assert actions.count("message_revision.created") == 2
    superseded = [e for e in events if e.to_state == "superseded"]
    assert len(superseded) == 1
    assert superseded[0].entity_id == str(first.id)
    assert superseded[0].from_state == "draft"


def test_the_created_event_records_the_hash(
    db_session: Session, draft: MessageDraft, recipient: ContactPoint
) -> None:
    revision = add_revision(db_session, draft, recipient)
    db_session.flush()

    event = (
        db_session.query(AuditEvent)
        .filter_by(entity_type="message_revision", entity_id=str(revision.id))
        .one()
    )

    assert event.payload["content_hash"] == revision.content_hash
