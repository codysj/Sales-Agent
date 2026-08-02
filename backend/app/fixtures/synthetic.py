"""The synthetic campaign world (specification §19.6 Stage 0/1, §24 item 4, GP-06).

Two campaigns — sodium storage and DC fast charging — with a product, an explicit readiness
version, target segments, a policy version, approved claims, and a published claim set each.
Stage 1 is synthetic-data-first, so this is what a developer, a test, or a demonstration runs
against; `Q-002`, `Q-017`, `Q-021`, and `Q-022` have delivered no approved segments, brief, or
claim set, and every string here is a visible placeholder rather than a guess at real wording.

No fixture string contains a digit, and `tests/test_fixtures.py` enforces that. It is a blunt
mechanical stand-in for the three things §15.7 says a placeholder must never carry — a roadmap
date, a price, or a certification number — and a blunt rule is one a reviewer can actually
check. Question IDs and specification sections belong in this docstring, not in the data.

Two properties are load-bearing:

* **Seeding is a get-or-create, never a republish.** `publish_policy_version` and
  `publish_claim_set` supersede-and-add by design, so calling them twice would leave a second
  version and a superseded first one. Seeding an already-seeded database must be a no-op, so
  every step checks for its natural key first (`slug`, `(claim_key, version)`, or "has a current
  version at all") and skips.
* **It refuses to run outside a development environment.** Not because production has no
  database, but because a synthetic claim marked approved is exactly the kind of row that must
  never exist next to real data (§15.7). `staging` is refused too: the safe list is explicit.

No audit event is written. Seeding is a developer command that builds a world, not a
consequential action inside one, and `record_audit_event` requires a correlation ID from the
request or job that caused it (§17.5) — there is neither here.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.versioning import (
    ModelConfigVersion,
    content_hash,
    effective_version,
)
from app.campaigns.models import Campaign, TargetSegment
from app.campaigns.policy import CampaignPolicy
from app.campaigns.service import get_current_policy_version, publish_policy_version
from app.core.settings import AppEnv, ModelProvider, Settings, get_settings
from app.drafts_and_approvals.jobs import DEFAULT_MODEL_CONFIG_KEY as DRAFT_CONFIG_KEY
from app.identity.models import User
from app.model_gateway.prompts import register_prompt_versions
from app.model_gateway.providers.fake import MODEL_NAME as FAKE_MODEL_NAME
from app.model_gateway.schemas import register_schema_versions
from app.products_and_claims.claim_models import ApprovedClaim, ApprovedClaimCampaign
from app.products_and_claims.claims import (
    claim_is_allowed_for_campaign,
    get_claim_set,
    publish_claim_set,
)
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
from app.products_and_claims.status import get_effective_status, next_version_number
from app.qualification.jobs import DEFAULT_MODEL_CONFIG_KEY as QUALIFY_CONFIG_KEY

#: Every seeded name carries this, so a row that reached a real campaign is obvious on sight.
SYNTHETIC_PREFIX: Final = "SYNTHETIC-"

#: Approver identity, not a person. `Q-005` has not named who may approve claims.
#:
#: An **email**, and an `app_user` row exists for it (`T-136a`). Three vocabularies used to name
#: one concept — this constant, the test factory's `approver-1`, and `principal.user.email` on the
#: production path — and none of them resolved to a user. `T-136b` turns these columns into
#: foreign keys, and a key needs something to point at; the mapping it will use is the email.
#: `example.invalid` is IANA-reserved and can never be delivered to (AGENTS.md rule 1).
SEED_APPROVER: Final = "synthetic-approver@example.invalid"

#: Display name for that user. Carries the prefix so a row that reached a real screen is obvious;
#: the email cannot, because `app_user` requires it lowercase.
SEED_APPROVER_NAME: Final = f"{SYNTHETIC_PREFIX}approver"

#: Claims must carry a review date (`expires_or_review_by` is NOT NULL, T-014). Six months keeps
#: a seeded database usable without making a placeholder claim effectively permanent.
CLAIM_REVIEW_INTERVAL: Final = timedelta(days=180)

#: Environments a seed may run in. An explicit allow-list: a new environment is refused until
#: someone decides otherwise.
SEEDABLE_ENVIRONMENTS: Final = frozenset({AppEnv.LOCAL, AppEnv.TEST})

#: Who publishes the versions this module registers. An `Actor` id, not a person (ADR-025): a
#: prompt or schema version is published by a process here, and `created_by` on a versioned
#: artefact is deliberately not a user column (`T-136` says so in `VersionedArtefact`).
SEED_PUBLISHER: Final = "fixtures.seed_synthetic"

#: The bounded tasks whose model configuration a locally-run worker needs (`T-172b`). Both name
#: the **fake** provider, which is the only member `ModelProvider` has: gate **G-03** is locked
#: and `Q-012` has approved no provider or its data-handling terms. A real deployment naming a
#: real provider is a different act, in a different place, behind that gate.
FAKE_MODEL_CONFIGS: Final = (QUALIFY_CONFIG_KEY, DRAFT_CONFIG_KEY)

#: Parameters recorded on those configurations. Zero temperature because a fixture-keyed lookup
#: has nothing to vary, and a run cites the parameters it used (§14.5).
FAKE_MODEL_PARAMETERS: Final[dict[str, object]] = {"temperature": 0}


class SeedRefused(Exception):
    """Seeding was attempted where synthetic data must not exist."""


@dataclass(frozen=True, slots=True)
class ClaimFixture:
    """One placeholder claim. `text` is what would be sent, so it says it is not real."""

    key: str
    text: str


@dataclass(frozen=True, slots=True)
class CampaignFixture:
    """One product, its readiness, and the campaign that may reference it."""

    product_slug: str
    product_name: str
    product_summary: str
    readiness: ReadinessCategory
    campaign_slug: str
    campaign_name: str
    campaign_description: str
    segments: tuple[str, ...]
    claims: tuple[ClaimFixture, ...]


#: ADR-012 and §8.6: both configurations exist, only one goes live first. Readiness is deliberately
#: never `sellable_now` — nothing may be positioned as generally available before `Q-021`/`Q-022`.
CAMPAIGN_FIXTURES: Final = (
    CampaignFixture(
        product_slug="synthetic-sodium-storage",
        product_name="SYNTHETIC-Sodium Storage Module",
        product_summary=(
            "SYNTHETIC placeholder for a sodium-chemistry stationary storage module. "
            "Stands in for an approved product brief that does not exist yet."
        ),
        readiness=ReadinessCategory.EVALUATION_OR_PILOT,
        campaign_slug="synthetic-sodium-battery",
        campaign_name="SYNTHETIC-Sodium Battery Campaign",
        campaign_description=(
            "SYNTHETIC campaign configuration for stationary storage outreach. Target segments "
            "are placeholders, not approved segments."
        ),
        segments=(
            "SYNTHETIC-segment-microgrid-operator",
            "SYNTHETIC-segment-industrial-site",
        ),
        claims=(
            ClaimFixture(
                key="SYNTHETIC-CLAIM-sodium-readiness",
                text=(
                    "SYNTHETIC EXAMPLE CLAIM — the SYNTHETIC-Sodium Storage Module is offered "
                    "for evaluation and pilot deployments. Placeholder wording, approved by "
                    "nobody, never for a real recipient."
                ),
            ),
            ClaimFixture(
                key="SYNTHETIC-CLAIM-sodium-positioning",
                text=(
                    "SYNTHETIC EXAMPLE CLAIM — the SYNTHETIC-Sodium Storage Module is positioned "
                    "for sites where a lithium chemistry is a poor fit. Placeholder wording, "
                    "approved by nobody, never for a real recipient."
                ),
            ),
        ),
    ),
    CampaignFixture(
        product_slug="synthetic-dc-fast-charging",
        product_name="SYNTHETIC-DC Fast Charging Package",
        product_summary=(
            "SYNTHETIC placeholder for an EV DC fast-charging package. Stands in for an approved "
            "product brief that does not exist yet."
        ),
        readiness=ReadinessCategory.IN_DEVELOPMENT,
        campaign_slug="synthetic-dc-fast-charging",
        campaign_name="SYNTHETIC-DC Fast Charging Campaign",
        campaign_description=(
            "SYNTHETIC campaign configuration for charging-infrastructure outreach. Target "
            "segments are placeholders, not approved segments."
        ),
        segments=(
            "SYNTHETIC-segment-fleet-depot",
            "SYNTHETIC-segment-highway-retail",
        ),
        claims=(
            ClaimFixture(
                key="SYNTHETIC-CLAIM-charging-readiness",
                text=(
                    "SYNTHETIC EXAMPLE CLAIM — the SYNTHETIC-DC Fast Charging Package is in "
                    "development and is not offered for delivery. Placeholder wording, approved "
                    "by nobody, never for a real recipient."
                ),
            ),
            ClaimFixture(
                key="SYNTHETIC-CLAIM-charging-scope",
                text=(
                    "SYNTHETIC EXAMPLE CLAIM — the SYNTHETIC-DC Fast Charging Package is "
                    "described as hardware with installation and support services. Placeholder "
                    "wording, approved by nobody, never for a real recipient."
                ),
            ),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class SeedResult:
    """What the run actually created. Empty on an already-seeded database."""

    created: tuple[str, ...]

    @property
    def was_noop(self) -> bool:
        return not self.created


def fixture_strings() -> tuple[str, ...]:
    """Every human-readable string in the fixture data, for the content checks in T-040."""
    values: list[str] = [SEED_APPROVER]
    for fixture in CAMPAIGN_FIXTURES:
        values.extend(
            [
                fixture.product_slug,
                fixture.product_name,
                fixture.product_summary,
                fixture.campaign_slug,
                fixture.campaign_name,
                fixture.campaign_description,
                *fixture.segments,
            ]
        )
        for claim in fixture.claims:
            values.extend([claim.key, claim.text])
    return tuple(values)


def seed_approver(session: Session) -> User | None:
    """The `app_user` the seeded approvals name, or `None` before the first seed (`T-136a`).

    A function rather than a constant lookup at the call site, because `T-136b` will need exactly
    this resolution — approver string to user row — in its migration and in every writer, and one
    definition of "who is `SEED_APPROVER`" is what stops those two disagreeing.
    """
    return session.execute(select(User).where(User.email == SEED_APPROVER)).scalar_one_or_none()


def require_seedable(settings: Settings) -> None:
    """Raise :class:`SeedRefused` unless this environment may hold synthetic data."""
    if settings.app_env not in SEEDABLE_ENVIRONMENTS:
        raise SeedRefused(
            f"refusing to seed synthetic fixtures with APP_ENV={settings.app_env.value}; "
            f"allowed: {', '.join(sorted(env.value for env in SEEDABLE_ENVIRONMENTS))} "
            f"(§15.7 — a synthetic claim must never sit beside real data)"
        )


def _get_product(session: Session, slug: str) -> Product | None:
    return session.execute(select(Product).where(Product.slug == slug)).scalar_one_or_none()


def _get_campaign(session: Session, slug: str) -> Campaign | None:
    return session.execute(select(Campaign).where(Campaign.slug == slug)).scalar_one_or_none()


def _get_claim(session: Session, claim_key: str) -> ApprovedClaim | None:
    """Version 1 of a claim key. The seeder never publishes a later version."""
    return session.execute(
        select(ApprovedClaim).where(
            ApprovedClaim.claim_key == claim_key, ApprovedClaim.version == 1
        )
    ).scalar_one_or_none()


def _has_segment(session: Session, campaign_id: uuid.UUID, key: str) -> bool:
    statement = select(TargetSegment.id).where(
        TargetSegment.campaign_id == campaign_id, TargetSegment.key == key
    )
    return session.execute(statement).first() is not None


def _seed_versions(session: Session, *, moment: datetime) -> list[str]:
    """Register the prompt, schema, and model-config versions a job handler resolves (`T-172b`).

    **Why this is here and not somewhere more obviously right.** `handle_qualify` and
    `handle_draft` call `require_effective_version` three times each and fail **permanently** when
    any is missing (§7.2 "validate policy and input version", §14.5). Nothing outside `tests/`
    registered any, so a database built by the documented commands produced candidates, researched
    them, and then stopped — with the reason inside a dead job. ADR-028 records the choice of home
    and what it does not solve: a **deployment** still has no path that registers these, which is
    `T-185`, and needs `Q-018` to have said what a deployment is.

    The two registrars are content-hash idempotent and are production code over production
    artefacts — the prompt `.txt` and schema `.json` files under `app/model_gateway/`. Nothing
    synthetic is being published; what makes this the right *caller* today is that
    `seed_synthetic` is the one step that runs before anything else locally.

    The model configurations **are** a local choice, and they name the fake provider only.
    """
    created: list[str] = []
    created += [
        f"prompt version {version.key}"
        for version in register_prompt_versions(session, created_by=SEED_PUBLISHER, at=moment)
    ]
    created += [
        f"schema version {version.key}"
        for version in register_schema_versions(session, created_by=SEED_PUBLISHER, at=moment)
    ]

    # One `if` per key rather than a loop that returns on the first (the `T-148` trap): a database
    # holding the qualification configuration and not the draft one must gain the draft one.
    for key in FAKE_MODEL_CONFIGS:
        if effective_version(session, ModelConfigVersion, key, at=moment) is not None:
            continue
        session.add(
            ModelConfigVersion(
                key=key,
                version=1,
                content_hash=content_hash(
                    {
                        "provider": ModelProvider.FAKE.value,
                        "model_name": FAKE_MODEL_NAME,
                        "parameters": FAKE_MODEL_PARAMETERS,
                    }
                ),
                effective_from=moment,
                created_by=SEED_PUBLISHER,
                provider=ModelProvider.FAKE,
                model_name=FAKE_MODEL_NAME,
                parameters=dict(FAKE_MODEL_PARAMETERS),
            )
        )
        session.flush()
        created.append(f"model config {key}")

    return created


def seed_synthetic(
    session: Session,
    *,
    settings: Settings | None = None,
    at: datetime | None = None,
) -> SeedResult:
    """Load :data:`CAMPAIGN_FIXTURES` into ``session``, skipping whatever already exists.

    Adds without committing, so the caller's transaction decides — the CLI commits, tests roll
    back. Raises :class:`SeedRefused` **before touching the database** outside a seedable
    environment.
    """
    require_seedable(settings or get_settings())
    moment = at or datetime.now(UTC)
    created: list[str] = []

    # Before anything writes `approved_by`: the approver has to be somebody (`T-136a`). Until now
    # every seeded approval named a string that resolved to no row at all, which is the reason
    # `T-136b`'s foreign key could not be added.
    if seed_approver(session) is None:
        session.add(
            User(email=SEED_APPROVER, display_name=SEED_APPROVER_NAME, subject=None, active=True)
        )
        session.flush()
        created.append(f"user {SEED_APPROVER}")

    created += _seed_versions(session, moment=moment)

    for fixture in CAMPAIGN_FIXTURES:
        product = _get_product(session, fixture.product_slug)
        if product is None:
            product = Product(
                slug=fixture.product_slug,
                name=fixture.product_name,
                description=fixture.product_summary,
            )
            session.add(product)
            session.flush()
            created.append(f"product {fixture.product_slug}")

        if get_effective_status(session, product.id, at=moment) is None:
            session.add(
                ProductStatusVersion(
                    product_id=product.id,
                    version=next_version_number(session, product.id),
                    readiness_category=fixture.readiness,
                    summary=fixture.product_summary,
                    approved_by=SEED_APPROVER,
                    approved_at=moment,
                    effective_from=moment,
                    # Open-ended: a fixture world that expires on a hidden date turns into a
                    # confusing "no effective readiness" failure weeks later.
                    expires_or_review_by=None,
                )
            )
            session.flush()
            created.append(f"product status {fixture.product_slug}")

        campaign = _get_campaign(session, fixture.campaign_slug)
        if campaign is None:
            # `paused` defaults to True (T-015) and stays that way: starting a campaign is a
            # deliberate act, not a side effect of loading fixtures.
            campaign = Campaign(
                slug=fixture.campaign_slug,
                name=fixture.campaign_name,
                description=fixture.campaign_description,
                product_id=product.id,
            )
            session.add(campaign)
            session.flush()
            created.append(f"campaign {fixture.campaign_slug}")

        for key in fixture.segments:
            if not _has_segment(session, campaign.id, key):
                session.add(TargetSegment(campaign_id=campaign.id, key=key))
                created.append(f"segment {key}")

        if get_current_policy_version(session, campaign.id) is None:
            publish_policy_version(
                session,
                campaign_id=campaign.id,
                policy=CampaignPolicy(),
                approved_by=SEED_APPROVER,
                approved_at=moment,
            )
            created.append(f"policy version {fixture.campaign_slug}")

        claims: list[ApprovedClaim] = []
        for claim_fixture in fixture.claims:
            claim = _get_claim(session, claim_fixture.key)
            if claim is None:
                claim = ApprovedClaim(
                    claim_key=claim_fixture.key,
                    version=1,
                    product_id=product.id,
                    text=claim_fixture.text,
                    presumes_readiness=fixture.readiness,
                    approved_by=SEED_APPROVER,
                    approved_at=moment,
                    effective_from=moment,
                    expires_or_review_by=moment + CLAIM_REVIEW_INTERVAL,
                    is_synthetic=True,
                )
                session.add(claim)
                session.flush()
                created.append(f"claim {claim_fixture.key}")
            if not claim_is_allowed_for_campaign(
                session, claim_id=claim.id, campaign_id=campaign.id
            ):
                session.add(ApprovedClaimCampaign(claim_id=claim.id, campaign_id=campaign.id))
                session.flush()
                created.append(f"claim scope {claim_fixture.key}")
            claims.append(claim)

        if get_claim_set(session, product_id=product.id, campaign_id=campaign.id) is None:
            publish_claim_set(
                session,
                product_id=product.id,
                campaign_id=campaign.id,
                claims=claims,
                approved_by=SEED_APPROVER,
                approved_at=moment,
            )
            created.append(f"claim set {fixture.campaign_slug}")

    session.flush()
    return SeedResult(created=tuple(created))
