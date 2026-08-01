"""The synthetic fixture seeder (T-040; specification §19.6 Stage 0/1, §24 item 4, GP-06, §15.7).

Three things are worth testing and one of them is not the happy path:

* seeding twice must change nothing, because the underlying publish helpers supersede-and-add;
* no fixture string may carry a roadmap date, a price, a certification, or a real name;
* seeding outside `local`/`test` must be refused before the database is touched at all.

The content checks run offline. Only the seeding tests need PostgreSQL.
"""

import re
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.campaigns.models import Campaign, CampaignPolicyVersion, TargetSegment
from app.core.settings import AppEnv, Settings
from app.fixtures.synthetic import (
    CAMPAIGN_FIXTURES,
    SEED_APPROVER,
    SYNTHETIC_PREFIX,
    SeedRefused,
    fixture_strings,
    seed_synthetic,
)
from app.products_and_claims.claim_models import (
    ApprovedClaim,
    ApprovedClaimSet,
    ApprovedClaimSetMember,
)
from app.products_and_claims.claims import get_valid_claim_set
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
from app.products_and_claims.status import require_effective_status
from tests.test_module_boundaries import APP, imported_app_packages

#: Vocabulary a placeholder claim must never use. Availability, certification, pricing, and
#: named customers are precisely what §15.7 says only an approved claim may assert.
FORBIDDEN_VOCABULARY = (
    "certif",
    "patent",
    "price",
    "pricing",
    "usd",
    "guarantee",
    "warrant",
    "available now",
    "in stock",
    "customer",
    "$",
    "%",
)


def _names() -> list[str]:
    """Identifiers, as opposed to prose: these must all carry the prefix, case aside."""
    names = [SEED_APPROVER]
    for fixture in CAMPAIGN_FIXTURES:
        names.extend(
            [
                fixture.product_slug,
                fixture.product_name,
                fixture.campaign_slug,
                fixture.campaign_name,
                *fixture.segments,
                *(claim.key for claim in fixture.claims),
            ]
        )
    return names


# --- content: criterion 2 ------------------------------------------------------------------


def test_every_fixture_name_carries_the_synthetic_prefix() -> None:
    offenders = [name for name in _names() if not name.lower().startswith(SYNTHETIC_PREFIX.lower())]

    assert not offenders, f"fixture names without the SYNTHETIC- prefix: {offenders}"


def test_every_fixture_prose_string_says_it_is_synthetic() -> None:
    """A description or claim body that reads as real is the one that gets pasted somewhere."""
    offenders = [value for value in fixture_strings() if "synthetic" not in value.lower()]

    assert not offenders, f"fixture strings that never say SYNTHETIC: {offenders}"


def test_no_fixture_string_contains_a_digit() -> None:
    """No digit means no roadmap date, no price, and no certification number (§15.7)."""
    offenders = [value for value in fixture_strings() if re.search(r"\d", value)]

    assert not offenders, f"fixture strings carrying digits: {offenders}"


def test_no_fixture_string_uses_claim_vocabulary_reserved_for_approved_claims() -> None:
    offenders = [
        (value, word)
        for value in fixture_strings()
        for word in FORBIDDEN_VOCABULARY
        if word in value.lower()
    ]

    assert not offenders, f"forbidden claim vocabulary in fixtures: {offenders}"


def test_no_fixture_readiness_claims_general_availability() -> None:
    """`sellable_now` is the one readiness a placeholder may never assert (GP-12)."""
    offenders = [
        fixture.product_slug
        for fixture in CAMPAIGN_FIXTURES
        if fixture.readiness is ReadinessCategory.SELLABLE_NOW
    ]

    assert not offenders, f"fixtures positioned as generally available: {offenders}"


def test_both_stage_one_campaigns_are_defined() -> None:
    """§24 items 2-3 and ADR-012: sodium storage and DC fast charging both get configured."""
    slugs = {fixture.campaign_slug for fixture in CAMPAIGN_FIXTURES}

    assert slugs == {"synthetic-sodium-battery", "synthetic-dc-fast-charging"}


# --- environment guard: criterion 3 --------------------------------------------------------


@pytest.mark.parametrize("app_env", [AppEnv.PRODUCTION, AppEnv.STAGING])
def test_seeding_is_refused_outside_a_seedable_environment(app_env: AppEnv) -> None:
    """`None` for the session is the assertion: the guard must fire before any database use."""
    with pytest.raises(SeedRefused, match=app_env.value):
        seed_synthetic(None, settings=Settings(app_env=app_env))  # type: ignore[arg-type]


# --- the fixtures must stay out of the production path -------------------------------------


def fixture_importers(files: dict[Path, str]) -> list[str]:
    """Modules importing `app.fixtures` that are not the CLI or the fixtures themselves."""
    offenders: list[str] = []
    for path, source in files.items():
        parts = path.relative_to(APP).parts
        if parts[0] in ("fixtures", "cli.py"):
            continue
        if "fixtures" in imported_app_packages(source):
            offenders.append("/".join(parts))
    return offenders


def test_only_the_cli_imports_the_fixtures() -> None:
    """A production path that needs a fixture is a production path that breaks on real data."""
    sources = {path: path.read_text(encoding="utf-8") for path in sorted(APP.rglob("*.py"))}

    assert not fixture_importers(sources), (
        f"synthetic fixtures reached from production code: {fixture_importers(sources)}"
    )


def test_the_fixture_import_check_can_fail() -> None:
    offending = {APP / "qualification" / "rules.py": "from app.fixtures.synthetic import x\n"}

    assert fixture_importers(offending) == ["qualification/rules.py"]


# --- seeding: criterion 1 ------------------------------------------------------------------

TEST_SETTINGS = Settings(app_env=AppEnv.TEST)


def _counts(session: Session) -> dict[str, int]:
    return {
        model.__name__: session.execute(select(func.count()).select_from(model)).scalar_one()
        for model in (
            Product,
            ProductStatusVersion,
            Campaign,
            TargetSegment,
            CampaignPolicyVersion,
            ApprovedClaim,
            ApprovedClaimSet,
            ApprovedClaimSetMember,
        )
    }


def test_seeding_creates_both_worlds(db_session: Session) -> None:
    result = seed_synthetic(db_session, settings=TEST_SETTINGS)

    assert not result.was_noop
    assert _counts(db_session) == {
        "Product": 2,
        "ProductStatusVersion": 2,
        "Campaign": 2,
        "TargetSegment": 4,
        "CampaignPolicyVersion": 2,
        "ApprovedClaim": 4,
        "ApprovedClaimSet": 2,
        "ApprovedClaimSetMember": 4,
    }


def test_seeding_twice_changes_nothing(db_session: Session) -> None:
    """Idempotence is not free here: `publish_claim_set` supersedes-and-adds by design."""
    seed_synthetic(db_session, settings=TEST_SETTINGS)
    before = _counts(db_session)
    identifiers = set(db_session.execute(select(ApprovedClaimSet.id)).scalars().all())

    second = seed_synthetic(db_session, settings=TEST_SETTINGS)

    assert second.was_noop, f"re-seeding created: {second.created}"
    assert _counts(db_session) == before
    assert set(db_session.execute(select(ApprovedClaimSet.id)).scalars().all()) == identifiers
    assert (
        db_session.execute(
            select(func.count())
            .select_from(ApprovedClaimSet)
            .where(ApprovedClaimSet.superseded_at.is_not(None))
        ).scalar_one()
        == 0
    )


def test_every_seeded_claim_is_marked_synthetic(db_session: Session) -> None:
    seed_synthetic(db_session, settings=TEST_SETTINGS)

    claims = db_session.execute(select(ApprovedClaim)).scalars().all()

    assert claims
    assert all(claim.is_synthetic for claim in claims)


def test_each_seeded_claim_set_resolves_against_its_campaign(db_session: Session) -> None:
    """The world is coherent: the fail-closed claim resolver accepts what the seeder published."""
    seed_synthetic(db_session, settings=TEST_SETTINGS)

    for fixture in CAMPAIGN_FIXTURES:
        campaign = db_session.execute(
            select(Campaign).where(Campaign.slug == fixture.campaign_slug)
        ).scalar_one()
        claim_set, claims = get_valid_claim_set(
            db_session, product_id=campaign.product_id, campaign_id=campaign.id
        )

        assert claim_set.version == 1
        assert {claim.claim_key for claim in claims} == {c.key for c in fixture.claims}
        assert require_effective_status(db_session, campaign.product_id).readiness_category is (
            fixture.readiness
        )


def test_seeded_campaigns_start_paused(db_session: Session) -> None:
    """Loading fixtures must not start work; starting a campaign is a deliberate act (T-015)."""
    seed_synthetic(db_session, settings=TEST_SETTINGS)

    campaigns = db_session.execute(select(Campaign)).scalars().all()

    assert campaigns
    assert all(campaign.paused for campaign in campaigns)


# --- T-060b: the committed OpenAPI document matches the application ------------------------------


def test_the_committed_openapi_document_matches_the_application() -> None:
    """Half of the drift check, and the half only Python can perform.

    `frontend/openapi.json` is the input the dashboard's types are generated from. If the backend
    adds a field or renames a response model and nobody re-exports, the committed document goes
    stale and the frontend generates types for an API that no longer exists — silently, because
    every frontend check would still pass against the stale file.

    The other half lives in `frontend/tests/api-types.test.ts`, which regenerates the types from
    this document and fails if the checked-in output was hand-edited. Together they close the
    loop: application -> document -> types, with a test on each arrow.
    """
    import json

    from scripts.export_openapi import OPENAPI_EXPORT_PATH, openapi_document

    assert OPENAPI_EXPORT_PATH.exists(), (
        f"{OPENAPI_EXPORT_PATH} is missing; run `uv run python -m scripts.export_openapi`"
    )
    committed = json.loads(OPENAPI_EXPORT_PATH.read_text(encoding="utf-8"))

    assert committed == openapi_document(), (
        "the committed OpenAPI document is stale; run `uv run python -m scripts.export_openapi`"
    )


def test_the_exported_document_is_byte_stable() -> None:
    """Two exports of the same application produce the same bytes.

    The file is committed and diffed, so a document whose key order moved between runs would show
    as a change nobody made — and a reviewer who sees noise stops reading the diff.
    """
    import json

    from scripts.export_openapi import openapi_document

    first = json.dumps(openapi_document(), indent=2, sort_keys=True)
    second = json.dumps(openapi_document(), indent=2, sort_keys=True)

    assert first == second


def test_the_document_describes_the_endpoints_that_exist() -> None:
    """A guard on the guard: an empty document would make the comparison above vacuously true."""
    import json

    from scripts.export_openapi import OPENAPI_EXPORT_PATH

    committed = json.loads(OPENAPI_EXPORT_PATH.read_text(encoding="utf-8"))

    # The full list, not a `>= 1` count: this exists so an empty or truncated document cannot
    # make the comparison above pass vacuously, and a length check would not notice a document
    # that had lost every path but one. Adding a route means updating this line, deliberately.
    assert sorted(committed["paths"]) == [
        "/api/auth/session",
        "/api/auth/stub-sign-in",
        "/api/review/approvals/{approval_id}/revoke",
        "/api/review/attention/approvals",
        "/api/review/candidates",
        "/api/review/candidates/{candidate_id}",
        "/api/review/candidates/{candidate_id}/approve",
        "/api/review/candidates/{candidate_id}/defer",
        "/api/review/candidates/{candidate_id}/reject",
        "/api/review/candidates/{candidate_id}/request-research",
        "/api/review/revisions",
        "/api/review/revisions/{revision_id}/approve",
        "/api/review/revisions/{revision_id}/edit",
        "/healthz",
        "/readyz",
    ]
