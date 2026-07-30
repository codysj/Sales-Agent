"""Resolving what a product's readiness currently is (specification §2.3, GP-12).

Reads fail closed. A product with no effective status version has *no* approved readiness, which
is not the same as "probably fine" — callers get ``None`` or an exception, never a stale row.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.products_and_claims.models import ProductStatusVersion


class ProductStatusError(Exception):
    """No usable readiness answer exists."""


class NoEffectiveProductStatus(ProductStatusError):
    """The product has no status version covering the requested instant.

    Raised rather than defaulted: guessing readiness is how a roadmap item becomes an
    availability claim (GP-12, §15.7).
    """


def get_effective_status(
    session: Session,
    product_id: uuid.UUID,
    *,
    at: datetime | None = None,
) -> ProductStatusVersion | None:
    """The status version in force at ``at`` (default: now), or ``None``.

    The exclusion constraint guarantees at most one row can match, so this cannot silently pick
    between overlapping answers.
    """
    moment = at or datetime.now(UTC)

    statement = (
        select(ProductStatusVersion)
        .where(
            ProductStatusVersion.product_id == product_id,
            ProductStatusVersion.effective_from <= moment,
        )
        .where(
            (ProductStatusVersion.expires_or_review_by.is_(None))
            | (ProductStatusVersion.expires_or_review_by > moment)
        )
    )
    return session.execute(statement).scalar_one_or_none()


def require_effective_status(
    session: Session,
    product_id: uuid.UUID,
    *,
    at: datetime | None = None,
) -> ProductStatusVersion:
    """As :func:`get_effective_status`, but raises instead of returning ``None``.

    Use this anywhere a missing readiness answer must stop the workflow — eligibility, drafting,
    and the final send checks (§11.4).
    """
    status = get_effective_status(session, product_id, at=at)
    if status is None:
        moment = at or datetime.now(UTC)
        raise NoEffectiveProductStatus(
            f"product {product_id} has no effective status version at {moment.isoformat()}; "
            f"readiness must be explicit before the product may be referenced (GP-12)"
        )
    return status


def next_version_number(session: Session, product_id: uuid.UUID) -> int:
    """The next per-product version number. The unique constraint is the real arbiter."""
    highest = session.execute(
        select(ProductStatusVersion.version)
        .where(ProductStatusVersion.product_id == product_id)
        .order_by(ProductStatusVersion.version.desc())
        .limit(1)
    ).scalar_one_or_none()
    return (highest or 0) + 1
