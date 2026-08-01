"""Prospect identity normalizes on write (T-016; §8.3 step 2, §13.5, §15.6).

The property that matters: two spellings of the same identity must collide. If they do not,
deduplication misses and — worse — a suppression recorded against one spelling will not stop a
send to the other (§15.6).

All fixtures use IANA reserved example domains. No real company, person, or address appears.
"""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    CRMMapping,
    CRMProvider,
    MappedRecordType,
    VerificationState,
)
from app.prospects.normalize import (
    NormalizationError,
    normalize_country,
    normalize_domain,
    normalize_email,
)


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


# --- domain normalization (criterion 2) ----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Example.COM", "example.com"),
        ("  example.com  ", "example.com"),
        ("www.example.com", "example.com"),
        ("WWW.Example.com", "example.com"),
        ("https://example.com", "example.com"),
        ("http://www.example.com", "example.com"),
        ("https://WWW.Example.com/about?x=1#frag", "example.com"),
        ("example.com.", "example.com"),
        ("example.com:8443", "example.com"),
        ("sub.example.com", "sub.example.com"),
    ],
)
def test_domains_normalize(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "no-dot", "has space.com", "://"])
def test_unusable_domains_are_rejected(raw: str) -> None:
    """Rejected, not silently coerced — a junk key would create a phantom account."""
    with pytest.raises(NormalizationError):
        normalize_domain(raw)


def test_account_domains_are_normalized_on_write(db_session: Session) -> None:
    item = Account(domain="https://WWW.Normalized.example.com/path", name="SYNTHETIC")
    db_session.add(item)
    db_session.flush()

    assert item.domain == "normalized.example.com"


def test_two_spellings_of_a_domain_collide(db_session: Session) -> None:
    db_session.add(Account(domain="collide.example.com", name="SYNTHETIC-First"))
    db_session.flush()
    db_session.add(Account(domain="https://WWW.Collide.Example.COM/", name="SYNTHETIC-Second"))

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- email normalization (criterion 1) -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("A@X.example.com", "a@x.example.com"),
        ("  Sales@Example.COM ", "sales@example.com"),
        ("MiXeD.CaSe@Example.Org", "mixed.case@example.org"),
    ],
)
def test_emails_normalize(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw", ["", "   ", "not-an-email", "no@domain", "two@@at.com", "a b@example.com"]
)
def test_unusable_emails_are_rejected(raw: str) -> None:
    with pytest.raises(NormalizationError):
        normalize_email(raw)


def test_plus_tags_and_dots_are_preserved(db_session: Session) -> None:
    """Provider-specific canonicalization is deliberately not applied.

    Gmail treats ``a.b@`` and ``ab@`` as one mailbox; most providers do not. Guessing that two
    addresses are the same person is worse than treating them as two.
    """
    assert normalize_email("First.Last+campaign@Example.com") == "first.last+campaign@example.com"


def test_contact_point_emails_are_normalized_on_write(
    db_session: Session, contact: Contact
) -> None:
    point = ContactPoint(
        contact_id=contact.id, type=ContactPointType.EMAIL, value="Person@Example.COM"
    )
    db_session.add(point)
    db_session.flush()

    assert point.value == "person@example.com"


def test_the_same_email_in_two_cases_collides(db_session: Session, contact: Contact) -> None:
    """The criterion-1 case: `A@X.example.com` and `a@x.example.com` must be one contact point."""
    db_session.add(
        ContactPoint(contact_id=contact.id, type=ContactPointType.EMAIL, value="A@X.example.com")
    )
    db_session.flush()
    db_session.add(
        ContactPoint(contact_id=contact.id, type=ContactPointType.EMAIL, value="a@x.example.com")
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_an_email_cannot_belong_to_two_contacts(db_session: Session, account: Account) -> None:
    """One mailbox is one person; two contacts sharing it would defeat suppression."""
    first = Contact(account_id=account.id, full_name="SYNTHETIC One")
    second = Contact(account_id=account.id, full_name="SYNTHETIC Two")
    db_session.add_all([first, second])
    db_session.flush()

    db_session.add(
        ContactPoint(contact_id=first.id, type=ContactPointType.EMAIL, value="shared@example.com")
    )
    db_session.flush()
    db_session.add(
        ContactPoint(contact_id=second.id, type=ContactPointType.EMAIL, value="Shared@Example.com")
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_non_email_contact_points_keep_their_casing(db_session: Session, contact: Contact) -> None:
    """A LinkedIn URL path can be case-sensitive; only emails are lowercased."""
    point = ContactPoint(
        contact_id=contact.id,
        type=ContactPointType.LINKEDIN_URL,
        value="  https://www.linkedin.com/in/Synthetic-Person  ",
    )
    db_session.add(point)
    db_session.flush()

    assert point.value == "https://www.linkedin.com/in/Synthetic-Person"


def test_contact_points_start_unverified(db_session: Session, contact: Contact) -> None:
    """Unverified is not a soft yes — policy requires verification before a send (`T-015`)."""
    point = ContactPoint(
        contact_id=contact.id, type=ContactPointType.EMAIL, value="new@example.com"
    )
    db_session.add(point)
    db_session.flush()

    assert point.verification_state is VerificationState.UNVERIFIED


# --- country normalization ------------------------------------------------------------------


@pytest.mark.parametrize(("raw", "expected"), [("us", "US"), (" us ", "US"), ("US", "US")])
def test_country_codes_normalize(raw: str, expected: str) -> None:
    assert normalize_country(raw) == expected


@pytest.mark.parametrize("raw", ["", "USA", "U", "1S", "united states"])
def test_unusable_country_codes_are_rejected(raw: str) -> None:
    with pytest.raises(NormalizationError):
        normalize_country(raw)


def test_account_country_is_normalized_on_write(db_session: Session) -> None:
    item = Account(domain="country.example.com", name="SYNTHETIC", country_code="us")
    db_session.add(item)
    db_session.flush()

    assert item.country_code == "US"


def test_country_may_be_unknown(db_session: Session) -> None:
    """Unknown geography stays NULL; campaign policy refuses it rather than assuming domestic."""
    item = Account(domain="unknown-country.example.com", name="SYNTHETIC")
    db_session.add(item)
    db_session.flush()

    assert item.country_code is None


# --- CRM mapping (criterion 3) --------------------------------------------------------------


def test_one_external_id_per_internal_record_and_provider(
    db_session: Session, account: Account
) -> None:
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="ext-1",
        )
    )
    db_session.flush()
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="ext-2",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_two_internal_records_cannot_claim_one_external_id(
    db_session: Session, account: Account
) -> None:
    """Otherwise both would fight over the same CRM record on the next sync."""
    other = Account(domain="other.example.com", name="SYNTHETIC-Other")
    db_session.add(other)
    db_session.flush()

    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="ext-shared",
        )
    )
    db_session.flush()
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=other.id,
            external_id="ext-shared",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_the_same_record_may_map_to_several_providers(
    db_session: Session, account: Account
) -> None:
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="ext-1",
        )
    )
    db_session.add(
        CRMMapping(
            provider=CRMProvider.HUBSPOT,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="ext-1",
        )
    )

    db_session.flush()  # must not raise


def test_accounts_and_contacts_share_no_mapping_namespace(
    db_session: Session, account: Account, contact: Contact
) -> None:
    """Record type is part of the key, so an account and a contact may share an external ID."""
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="1234",
        )
    )
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.CONTACT,
            internal_id=contact.id,
            external_id="1234",
        )
    )

    db_session.flush()  # must not raise


def test_blank_external_ids_are_rejected(db_session: Session, account: Account) -> None:
    db_session.add(
        CRMMapping(
            provider=CRMProvider.FAKE,
            record_type=MappedRecordType.ACCOUNT,
            internal_id=account.id,
            external_id="   ",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- structure -------------------------------------------------------------------------------


def test_deleting_an_account_removes_its_contacts_and_points(
    db_session: Session, account: Account, contact: Contact
) -> None:
    db_session.add(
        ContactPoint(
            contact_id=contact.id, type=ContactPointType.EMAIL, value="cascade@example.com"
        )
    )
    db_session.flush()

    db_session.delete(account)
    db_session.flush()

    assert db_session.query(Contact).filter_by(id=contact.id).one_or_none() is None
    assert db_session.query(ContactPoint).count() == 0
