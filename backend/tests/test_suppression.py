"""Suppression outranks and outlives everything (T-017; §15.6, §3.5, §11.4).

"Zero sends to suppressed recipients" is a safety invariant. These tests hold the schema to the
three ways that invariant is normally lost: the record gets deleted with the contact, a wider
scope is not consulted, or campaign configuration is allowed to override it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.campaigns.policy import CampaignPolicy
from app.prospects.models import Account, Contact, ContactPoint, ContactPointType
from app.prospects.suppression import (
    UNLIFTABLE_SOURCES,
    RecipientSuppressed,
    Suppression,
    SuppressionError,
    SuppressionScope,
    SuppressionSource,
    find_suppression,
    is_suppressed,
    record_opt_out,
    record_suppression,
    require_not_suppressed,
)
from tests.factories import NOW

EARLIER = NOW - timedelta(days=1)
LATER = NOW + timedelta(days=1)


@pytest.fixture
def account(db_session: Session) -> Account:
    item = Account(domain=f"{uuid.uuid4().hex[:8]}.example.com", name="SYNTHETIC-Account")
    db_session.add(item)
    db_session.flush()
    return item


@pytest.fixture
def contact(db_session: Session, account: Account) -> Contact:
    item = Contact(account_id=account.id, full_name="SYNTHETIC Person")
    db_session.add(item)
    db_session.flush()
    return item


def suppress(
    db_session: Session, scope: SuppressionScope, identity: str, **kw: object
) -> Suppression:
    record = record_suppression(
        db_session,
        scope=scope,
        identity=identity,
        source=kw.pop("source", SuppressionSource.MANUAL),  # type: ignore[arg-type]
        reason=kw.pop("reason", "SYNTHETIC test suppression"),  # type: ignore[arg-type]
        effective_at=kw.pop("effective_at", EARLIER),  # type: ignore[arg-type]
        **kw,  # type: ignore[arg-type]
    )
    db_session.flush()
    return record


# --- scope coverage -------------------------------------------------------------------------------


def test_an_email_suppression_matches(db_session: Session) -> None:
    suppress(db_session, SuppressionScope.EMAIL, "blocked@example.com")

    assert is_suppressed(db_session, email="blocked@example.com", at=NOW)


def test_email_suppression_is_case_insensitive(db_session: Session) -> None:
    """Recorded in one spelling, must stop a send addressed in another (§15.6)."""
    suppress(db_session, SuppressionScope.EMAIL, "Blocked@Example.COM")

    assert is_suppressed(db_session, email="blocked@example.com", at=NOW)
    assert is_suppressed(db_session, email="BLOCKED@EXAMPLE.COM", at=NOW)


def test_a_domain_suppression_catches_a_new_contact_at_that_domain(db_session: Session) -> None:
    """Criterion 2: no additional write is needed for someone who did not exist yet."""
    suppress(db_session, SuppressionScope.DOMAIN, "blocked-domain.example.com")

    assert is_suppressed(db_session, email="brand.new.person@blocked-domain.example.com", at=NOW)


def test_a_domain_suppression_normalizes_what_it_was_given(db_session: Session) -> None:
    suppress(db_session, SuppressionScope.DOMAIN, "https://WWW.Blocked2.example.com/path")

    assert is_suppressed(db_session, email="anyone@blocked2.example.com", at=NOW)


def test_a_person_suppression_matches_the_contact(db_session: Session, contact: Contact) -> None:
    suppress(db_session, SuppressionScope.PERSON, str(contact.id))

    assert is_suppressed(db_session, contact_id=contact.id, at=NOW)


def test_an_account_suppression_matches_the_account(db_session: Session, account: Account) -> None:
    suppress(db_session, SuppressionScope.ACCOUNT, str(account.id))

    assert is_suppressed(db_session, account_id=account.id, at=NOW)


def test_an_unrelated_recipient_is_not_suppressed(db_session: Session) -> None:
    suppress(db_session, SuppressionScope.EMAIL, "someone@example.com")

    assert not is_suppressed(db_session, email="other@example.org", at=NOW)


def test_the_narrowest_match_is_reported(db_session: Session) -> None:
    """Any match suppresses; the order only decides which reason the operator sees."""
    suppress(db_session, SuppressionScope.DOMAIN, "both.example.com", reason="domain reason")
    suppress(db_session, SuppressionScope.EMAIL, "person@both.example.com", reason="email reason")

    match = find_suppression(db_session, email="person@both.example.com", at=NOW)

    assert match is not None
    assert match.scope is SuppressionScope.EMAIL


# --- survival (criterion 1) -----------------------------------------------------------------------


def test_deleting_a_contact_leaves_the_suppression_intact(
    db_session: Session, account: Account, contact: Contact
) -> None:
    """§15.6: contact deletion must not delete the suppression record."""
    db_session.add(
        ContactPoint(contact_id=contact.id, type=ContactPointType.EMAIL, value="gone@example.com")
    )
    db_session.flush()
    suppress(db_session, SuppressionScope.EMAIL, "gone@example.com")
    suppress(db_session, SuppressionScope.PERSON, str(contact.id))

    db_session.delete(contact)
    db_session.flush()

    assert db_session.query(Contact).filter_by(id=contact.id).one_or_none() is None
    assert is_suppressed(db_session, email="gone@example.com", at=NOW)
    assert is_suppressed(db_session, contact_id=contact.id, at=NOW)


def test_deleting_the_whole_account_leaves_suppressions_intact(
    db_session: Session, account: Account, contact: Contact
) -> None:
    suppress(db_session, SuppressionScope.ACCOUNT, str(account.id))
    suppress(db_session, SuppressionScope.DOMAIN, account.domain)

    db_session.delete(account)
    db_session.flush()

    assert is_suppressed(db_session, account_id=account.id, at=NOW)
    assert is_suppressed(db_session, email=f"anyone@{account.domain}", at=NOW)


def test_suppressions_cannot_be_deleted(db_session: Session) -> None:
    """A suppression you can drop is not a suppression."""
    record = suppress(db_session, SuppressionScope.EMAIL, "permanent@example.com")

    with pytest.raises(DBAPIError) as exc:
        db_session.execute(text("DELETE FROM suppression WHERE id = :id"), {"id": record.id})

    assert "cannot be removed" in str(exc.value)


def test_suppressions_cannot_be_truncated(db_session: Session) -> None:
    suppress(db_session, SuppressionScope.EMAIL, "permanent2@example.com")

    with pytest.raises(DBAPIError):
        db_session.execute(text("TRUNCATE suppression"))


def test_the_suppression_table_has_no_foreign_keys(db_session: Session) -> None:
    """Structural guarantee behind survival: nothing can cascade a suppression away."""
    rows = db_session.execute(
        text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = 'suppression'::regclass AND contype = 'f'"
        )
    ).all()

    assert rows == []


# --- precedence over campaign policy (criterion 3) ------------------------------------------------


def test_suppression_overrides_a_fully_permissive_campaign_policy(db_session: Session) -> None:
    """§15.6: a global unsubscribe overrides campaign configuration."""
    permissive = CampaignPolicy(
        allowed_countries=("US",), excluded_domains=(), require_verified_email=False
    )
    suppress(
        db_session,
        SuppressionScope.EMAIL,
        "optout@example.com",
        source=SuppressionSource.UNSUBSCRIBE,
        reason="unsubscribed",
    )

    # The policy permits everything relevant...
    assert permissive.permits_country("US")
    assert not permissive.excludes_domain("example.com")

    # ...and the recipient is still refused.
    with pytest.raises(RecipientSuppressed):
        require_not_suppressed(db_session, email="optout@example.com", at=NOW)


def test_the_send_time_check_takes_no_campaign_argument() -> None:
    """There is no configuration under which a suppressed recipient may be contacted (§11.4)."""
    import inspect

    parameters = set(inspect.signature(require_not_suppressed).parameters)

    assert "campaign_id" not in parameters
    assert "campaign" not in parameters
    assert "policy" not in parameters


def test_requiring_a_clean_recipient_passes(db_session: Session) -> None:
    require_not_suppressed(db_session, email="fine@example.com", at=NOW)  # must not raise


def test_the_error_names_the_scope_and_source(db_session: Session) -> None:
    suppress(
        db_session,
        SuppressionScope.DOMAIN,
        "named.example.com",
        source=SuppressionSource.COMPLAINT,
    )

    with pytest.raises(RecipientSuppressed) as exc:
        require_not_suppressed(db_session, email="someone@named.example.com", at=NOW)

    assert "domain" in str(exc.value)
    assert "complaint" in str(exc.value)


# --- timing ---------------------------------------------------------------------------------------


def test_a_suppression_applies_immediately(db_session: Session) -> None:
    """§15.6: suppression changes apply immediately across active campaigns."""
    assert not is_suppressed(db_session, email="later@example.com", at=NOW)

    suppress(db_session, SuppressionScope.EMAIL, "later@example.com", effective_at=NOW)

    assert is_suppressed(db_session, email="later@example.com", at=NOW)


def test_a_future_dated_suppression_is_not_yet_active(db_session: Session) -> None:
    suppress(db_session, SuppressionScope.EMAIL, "future@example.com", effective_at=LATER)

    assert not is_suppressed(db_session, email="future@example.com", at=NOW)
    assert is_suppressed(db_session, email="future@example.com", at=LATER)


# --- lifting --------------------------------------------------------------------------------------


def test_an_operator_error_can_be_lifted(db_session: Session) -> None:
    """A mistyped domain must be correctable, or one typo kills a campaign forever."""
    record = suppress(
        db_session,
        SuppressionScope.DOMAIN,
        "typo.example.com",
        source=SuppressionSource.MANUAL,
    )

    record.lifted_at = NOW
    record.lifted_by = "operator-1"
    record.lifted_reason = "recorded against the wrong domain"
    db_session.flush()

    assert not is_suppressed(db_session, email="anyone@typo.example.com", at=LATER)
    assert is_suppressed(
        db_session, email="anyone@typo.example.com", at=EARLIER + timedelta(hours=1)
    )


@pytest.mark.parametrize("source", sorted(UNLIFTABLE_SOURCES, key=lambda s: s.value))
def test_an_opt_out_can_never_be_lifted(db_session: Session, source: SuppressionSource) -> None:
    """Honouring an opt-out is a CAN-SPAM obligation (§15.8), not a preference."""
    record = suppress(
        db_session, SuppressionScope.EMAIL, f"{source.value}@example.com", source=source
    )

    record.lifted_at = NOW
    record.lifted_by = "operator-1"
    record.lifted_reason = "changed my mind on their behalf"

    with pytest.raises(DBAPIError) as exc:
        db_session.flush()

    assert "cannot be lifted" in str(exc.value)


def test_lifting_requires_a_reason(db_session: Session) -> None:
    record = suppress(db_session, SuppressionScope.EMAIL, "noreason@example.com")

    record.lifted_at = NOW

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- immutability ---------------------------------------------------------------------------------


def test_the_identity_cannot_be_rewritten(db_session: Session) -> None:
    record = suppress(db_session, SuppressionScope.EMAIL, "original@example.com")

    record.identity = "different@example.com"

    with pytest.raises(DBAPIError) as exc:
        db_session.flush()

    assert "immutable" in str(exc.value)


def test_the_source_cannot_be_downgraded(db_session: Session) -> None:
    """Otherwise an unsubscribe could be relabelled `MANUAL` and then lifted."""
    record = suppress(
        db_session,
        SuppressionScope.EMAIL,
        "downgrade@example.com",
        source=SuppressionSource.UNSUBSCRIBE,
    )

    record.source = SuppressionSource.MANUAL

    with pytest.raises(DBAPIError):
        db_session.flush()


def test_blank_reasons_are_rejected(db_session: Session) -> None:
    db_session.add(
        Suppression(
            scope=SuppressionScope.EMAIL,
            identity="blank@example.com",
            source=SuppressionSource.MANUAL,
            reason="   ",
            effective_at=EARLIER,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- opt-out intake (T-102a; §15.8 "clear opt-out handling and immediate suppression") ------------


def _rows_for(db_session: Session, identity: str) -> list[Suppression]:
    return list(
        db_session.execute(select(Suppression).where(Suppression.identity == identity))
        .scalars()
        .all()
    )


def test_the_same_opt_out_twice_records_one_suppression(db_session: Session) -> None:
    """`T-102a` criterion 2. Suppressions cannot be deleted (§15.6), so a duplicate is permanent
    noise in the one table an operator reads to answer "why was this person not contacted".

    The second delivery is spelled differently on purpose: idempotency has to key on the
    normalized identity, or a provider echoing back `Twice@EXAMPLE.com` defeats it.
    """
    first = record_opt_out(db_session, email="twice@example.com", reason="SYNTHETIC unsubscribe")
    db_session.flush()

    second = record_opt_out(db_session, email="Twice@EXAMPLE.com", reason="SYNTHETIC again")
    db_session.flush()

    assert len(_rows_for(db_session, "twice@example.com")) == 1
    assert [row.id for row in first] == [row.id for row in second]


def test_an_opt_out_is_never_future_dated(db_session: Session) -> None:
    """`T-102a` criterion 3. A provider clock running ahead, or a replayed event carrying its
    original timestamp, would otherwise leave a window in which the send transaction still lets
    the message through — `effective_at` is checked with `<=`."""
    far_future = datetime.now(UTC) + timedelta(days=30)

    [record] = record_opt_out(
        db_session, email="future@example.com", reason="SYNTHETIC unsubscribe", at=far_future
    )
    db_session.flush()

    assert record.effective_at <= datetime.now(UTC)
    assert is_suppressed(db_session, email="future@example.com", at=datetime.now(UTC))


def test_an_opt_out_recorded_earlier_keeps_the_earlier_moment(db_session: Session) -> None:
    """The clamp is one-directional. Suppressing *earlier* than now is the safe direction, so a
    late-delivered unsubscribe keeps the time the person actually sent it."""
    [record] = record_opt_out(
        db_session, email="backdated@example.com", reason="SYNTHETIC unsubscribe", at=EARLIER
    )
    db_session.flush()

    assert record.effective_at == EARLIER


@pytest.mark.parametrize(
    "source", sorted(set(SuppressionSource) - UNLIFTABLE_SOURCES, key=lambda item: item.value)
)
def test_an_opt_out_may_not_be_recorded_under_a_liftable_source(
    db_session: Session, source: SuppressionSource
) -> None:
    """`T-102a` criterion 4. Recording an opt-out as `MANUAL` leaves it liftable with a reason,
    which is the one property it must never have. Refused, not quietly downgraded."""
    with pytest.raises(SuppressionError) as exc:
        record_opt_out(db_session, email="liftable@example.com", reason="SYNTHETIC", source=source)

    assert source.value in str(exc.value)
    assert _rows_for(db_session, "liftable@example.com") == []


@pytest.mark.parametrize("source", sorted(UNLIFTABLE_SOURCES, key=lambda item: item.value))
def test_both_permanent_sources_are_accepted(
    db_session: Session, source: SuppressionSource
) -> None:
    """A spam complaint is an opt-out too, and it is just as permanent."""
    [record] = record_opt_out(
        db_session, email=f"{source.value}@example.com", reason="SYNTHETIC", source=source
    )
    db_session.flush()

    assert record.source is source


def test_an_opt_out_records_the_person_as_well_as_the_mailbox(
    db_session: Session, contact: Contact
) -> None:
    """The person asked not to be contacted, not the mailbox. A second address on the same
    contact must not undo it."""
    records = record_opt_out(
        db_session,
        email="person@example.com",
        reason="SYNTHETIC unsubscribe",
        contact_id=contact.id,
    )
    db_session.flush()

    assert {row.scope for row in records} == {SuppressionScope.EMAIL, SuppressionScope.PERSON}
    assert is_suppressed(db_session, contact_id=contact.id, at=datetime.now(UTC))


def test_an_opt_out_stops_the_final_send_transaction(db_session: Session) -> None:
    """The §11.4 form, which is where a send is actually refused."""
    record_opt_out(db_session, email="stop@example.com", reason="SYNTHETIC unsubscribe")
    db_session.flush()

    with pytest.raises(RecipientSuppressed):
        require_not_suppressed(db_session, email="stop@example.com")


def test_a_liftable_suppression_does_not_stand_in_for_an_opt_out(db_session: Session) -> None:
    """The half of idempotency that must *not* deduplicate.

    A `MANUAL` suppression on the same address can be lifted with a recorded reason. If it
    satisfied the opt-out, lifting it would silently un-suppress someone who had asked to be left
    alone — so the opt-out is written alongside it.
    """
    suppress(
        db_session,
        SuppressionScope.EMAIL,
        "manual@example.com",
        source=SuppressionSource.MANUAL,
    )

    [record] = record_opt_out(db_session, email="manual@example.com", reason="SYNTHETIC unsub")
    db_session.flush()

    assert record.source is SuppressionSource.UNSUBSCRIBE
    assert len(_rows_for(db_session, "manual@example.com")) == 2
