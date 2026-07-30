"""Product readiness is explicit, versioned, and non-overlapping (T-013; §2.3, §14.4, GP-12).

"Technical relevance does not imply availability, certification, or approval for a claim"
(GP-12). These tests hold the schema to that: a reader can never get two readiness answers, and
never gets a stale one.

Every product here is synthetic. No real Matrix Power specification, certification, roadmap date,
or MOU figure may appear in a fixture until `Q-021`/`Q-022` deliver approved briefs.
"""

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.products_and_claims.models import (
    Product,
    ProductStatusVersion,
    ReadinessCategory,
    SourceDocument,
)
from app.products_and_claims.status import (
    NoEffectiveProductStatus,
    get_effective_status,
    next_version_number,
    require_effective_status,
)

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
EARLIER = NOW - timedelta(days=30)
LATER = NOW + timedelta(days=30)


@pytest.fixture
def product(db_session: Session) -> Product:
    item = Product(slug=f"synthetic-battery-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Battery")
    db_session.add(item)
    db_session.flush()
    return item


def _status(product: Product, **overrides: object) -> ProductStatusVersion:
    values: dict[str, object] = {
        "product_id": product.id,
        "version": 1,
        "readiness_category": ReadinessCategory.EVALUATION_OR_PILOT,
        "approved_by": "product-owner-1",
        "approved_at": EARLIER,
        "effective_from": EARLIER,
        "expires_or_review_by": None,
    }
    values.update(overrides)
    return ProductStatusVersion(**values)  # type: ignore[arg-type]


# --- readiness is an enum, not prose -------------------------------------------------------


def test_the_five_readiness_categories_from_the_specification_exist() -> None:
    assert {category.value for category in ReadinessCategory} == {
        "sellable_now",
        "evaluation_or_pilot",
        "in_development",
        "strategic_or_roadmap",
        "paused_or_unavailable",
    }


def test_readiness_category_is_a_database_enum(db_session: Session, product: Product) -> None:
    """Free text would let "roughly available" through; the database refuses."""
    db_session.add(_status(product, readiness_category="probably_fine"))

    with pytest.raises(DBAPIError):
        db_session.flush()


# --- exactly one effective status per instant ----------------------------------------------


def test_overlapping_windows_are_rejected_by_the_database(
    db_session: Session, product: Product
) -> None:
    """Two concurrent writers must not be able to create two "current" answers."""
    db_session.add(_status(product, version=1, effective_from=EARLIER, expires_or_review_by=LATER))
    db_session.flush()

    db_session.add(_status(product, version=2, effective_from=NOW, expires_or_review_by=None))

    with pytest.raises(IntegrityError) as exc:
        db_session.flush()

    assert "ex_product_status_version_no_overlap" in str(exc.value)


def test_two_open_ended_windows_cannot_coexist(db_session: Session, product: Product) -> None:
    db_session.add(_status(product, version=1, effective_from=EARLIER))
    db_session.flush()

    db_session.add(_status(product, version=2, effective_from=NOW))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_clean_handover_is_allowed(db_session: Session, product: Product) -> None:
    """One window ending exactly where the next begins is a succession, not an overlap."""
    db_session.add(_status(product, version=1, effective_from=EARLIER, expires_or_review_by=NOW))
    db_session.add(_status(product, version=2, effective_from=NOW, expires_or_review_by=None))

    db_session.flush()  # must not raise

    assert get_effective_status(db_session, product.id, at=NOW - timedelta(seconds=1)) is not None


def test_other_products_are_unaffected(db_session: Session, product: Product) -> None:
    """The constraint is scoped per product, not global."""
    other = Product(slug=f"synthetic-charger-{uuid.uuid4().hex[:8]}", name="SYNTHETIC-Charger")
    db_session.add(other)
    db_session.flush()

    db_session.add(_status(product, effective_from=EARLIER))
    db_session.add(_status(other, effective_from=EARLIER))

    db_session.flush()  # must not raise


# --- expiry fails closed -------------------------------------------------------------------


def test_an_expired_status_is_never_returned_as_current(
    db_session: Session, product: Product
) -> None:
    """GP-12: a stale readiness answer is worse than none."""
    db_session.add(_status(product, effective_from=EARLIER, expires_or_review_by=NOW))
    db_session.flush()

    assert get_effective_status(db_session, product.id, at=NOW + timedelta(seconds=1)) is None


def test_a_status_is_not_current_before_it_takes_effect(
    db_session: Session, product: Product
) -> None:
    db_session.add(_status(product, effective_from=LATER))
    db_session.flush()

    assert get_effective_status(db_session, product.id, at=NOW) is None


def test_the_effective_status_is_returned_inside_its_window(
    db_session: Session, product: Product
) -> None:
    db_session.add(
        _status(
            product,
            readiness_category=ReadinessCategory.SELLABLE_NOW,
            effective_from=EARLIER,
            expires_or_review_by=LATER,
        )
    )
    db_session.flush()

    current = get_effective_status(db_session, product.id, at=NOW)

    assert current is not None
    assert current.readiness_category is ReadinessCategory.SELLABLE_NOW


def test_requiring_a_missing_status_raises(db_session: Session, product: Product) -> None:
    """Anywhere readiness must be known, absence stops the workflow rather than defaulting."""
    with pytest.raises(NoEffectiveProductStatus) as exc:
        require_effective_status(db_session, product.id, at=NOW)

    assert str(product.id) in str(exc.value)


def test_requiring_an_expired_status_raises(db_session: Session, product: Product) -> None:
    db_session.add(_status(product, effective_from=EARLIER, expires_or_review_by=NOW))
    db_session.flush()

    with pytest.raises(NoEffectiveProductStatus):
        require_effective_status(db_session, product.id, at=LATER)


def test_is_effective_at_agrees_with_the_query(db_session: Session, product: Product) -> None:
    version = _status(product, effective_from=EARLIER, expires_or_review_by=LATER)
    db_session.add(version)
    db_session.flush()

    assert version.is_effective_at(NOW)
    assert not version.is_effective_at(EARLIER - timedelta(seconds=1))
    assert not version.is_effective_at(LATER)
    assert (get_effective_status(db_session, product.id, at=NOW) is not None) is True


# --- versioning and supersession -----------------------------------------------------------


def test_version_numbers_are_unique_per_product(db_session: Session, product: Product) -> None:
    db_session.add(_status(product, version=1, effective_from=EARLIER, expires_or_review_by=NOW))
    db_session.flush()
    db_session.add(_status(product, version=1, effective_from=NOW))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_next_version_number_counts_up(db_session: Session, product: Product) -> None:
    assert next_version_number(db_session, product.id) == 1

    db_session.add(_status(product, version=1, effective_from=EARLIER, expires_or_review_by=NOW))
    db_session.flush()

    assert next_version_number(db_session, product.id) == 2


def test_a_version_records_what_it_supersedes(db_session: Session, product: Product) -> None:
    first = _status(product, version=1, effective_from=EARLIER, expires_or_review_by=NOW)
    db_session.add(first)
    db_session.flush()

    second = _status(product, version=2, effective_from=NOW, supersedes_version_id=first.id)
    db_session.add(second)
    db_session.flush()

    assert second.supersedes_version_id == first.id


def test_version_must_be_positive(db_session: Session, product: Product) -> None:
    db_session.add(_status(product, version=0))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_a_window_cannot_end_before_it_starts(db_session: Session, product: Product) -> None:
    db_session.add(_status(product, effective_from=LATER, expires_or_review_by=EARLIER))

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_approver_is_required(db_session: Session, product: Product) -> None:
    """§14.4 requires an approver; a blank one is not an approval."""
    db_session.add(_status(product, approved_by="   "))

    with pytest.raises(IntegrityError):
        db_session.flush()


# --- provenance ------------------------------------------------------------------------------


def test_a_status_can_cite_the_document_it_came_from(db_session: Session, product: Product) -> None:
    document = SourceDocument(
        title="SYNTHETIC-internal deck",
        document_type="deck",
        source_date=date(2026, 6, 1),
        is_internal=True,
    )
    db_session.add(document)
    db_session.flush()

    version = _status(product, source_document_id=document.id, source_date=document.source_date)
    db_session.add(version)
    db_session.flush()

    assert version.source_document_id == document.id


def test_a_cited_source_document_cannot_be_deleted(db_session: Session, product: Product) -> None:
    """Deleting the justification for a readiness claim must not happen quietly."""
    document = SourceDocument(
        title="SYNTHETIC-brief", document_type="brief", source_date=date(2026, 6, 1)
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(_status(product, source_document_id=document.id))
    db_session.flush()

    db_session.delete(document)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_source_documents_default_to_internal(db_session: Session) -> None:
    """Internal material is not an approved external claim (§15.7)."""
    document = SourceDocument(
        title="SYNTHETIC-notes", document_type="notes", source_date=date(2026, 6, 1)
    )
    db_session.add(document)
    db_session.flush()

    assert document.is_internal is True
