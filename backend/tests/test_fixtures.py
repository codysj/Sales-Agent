"""The synthetic fixture seeder (T-040; specification §19.6 Stage 0/1, §24 item 4, GP-06, §15.7).

Three things are worth testing and one of them is not the happy path:

* seeding twice must change nothing, because the underlying publish helpers supersede-and-add;
* no fixture string may carry a roadmap date, a price, a certification, or a real name;
* seeding outside `local`/`test` must be refused before the database is touched at all.

The content checks run offline. Only the seeding tests need PostgreSQL.
"""

import json
import re
from pathlib import Path

import pytest
import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.campaigns.models import Campaign, CampaignPolicyVersion, TargetSegment
from app.core.settings import AppEnv, Settings
from app.fixtures.model_routing import (
    DRAFT_OUTPUTS_BY_CAMPAIGN_NAME,
    DRAFT_PROMPT_MARKER,
    QUALIFICATION_OUTPUTS,
    NoFixtureSetForPrompt,
    TaskRoutingFake,
)
from app.fixtures.synthetic import (
    CAMPAIGN_FIXTURES,
    SEED_APPROVER,
    SYNTHETIC_PREFIX,
    SeedRefused,
    fixture_strings,
    seed_approver,
    seed_synthetic,
)
from app.identity.models import User
from app.model_gateway.prompts import prompt_template
from app.model_gateway.providers.fake import SENTINEL_PREFIX, resolve_evidence_sentinels
from app.products_and_claims.claim_models import (
    ApprovedClaim,
    ApprovedClaimSet,
    ApprovedClaimSetMember,
)
from app.products_and_claims.claims import get_valid_claim_set
from app.products_and_claims.models import Product, ProductStatusVersion, ReadinessCategory
from app.products_and_claims.status import require_effective_status
from tests.factories import World
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


#: Words a draft fixture uses to attribute a prospect fact to a source (`T-206`). A fixture may
#: now cite evidence — `T-207` gave it the `SYNTHETIC-EVIDENCE-N` sentinel — but what it cites is
#: an excerpt saying *"is described as"*, and naming a public announcement or a listing asserts a
#: provenance no stored fact carries. Citing is the mechanism; the wording is still a claim.
INVENTED_PROVENANCE = (
    "announcement",
    "listing",
    "press release",
    "according to",
    "report",
    "filing",
)


def draft_personalizations() -> list[tuple[str, str]]:
    """Every `personalization` string in a model-output draft fixture, with its file name."""
    root = Path(__file__).resolve().parents[1] / "app" / "fixtures" / "model_outputs"
    found: list[tuple[str, str]] = []
    for path in sorted(root.rglob("draft-*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload.get("output", {}).get("personalization")
        if isinstance(value, str):
            found.append((path.name, value))
    return found


def test_the_personalization_scan_finds_the_fixtures_it_checks() -> None:
    # Guard on the guard: an empty scan would make the check below vacuously true.
    found = draft_personalizations()

    assert len(found) >= 2, f"the draft-fixture scan found {len(found)}; it is misreading"


def test_no_draft_fixture_attributes_a_prospect_fact_to_a_source_it_cannot_cite() -> None:
    """`T-206`, and the rehearsal is the reason it exists.

    Both default draft fixtures said the account was described *"in a public announcement"* /
    *"in a public listing"*. The stored excerpts said only *"is described as"*. Three independent
    readers in `T-071c` caught it by comparing draft to evidence — the exact thing a reviewer is
    for — and every automated check passed it, because `_check_evidence_citations` verifies that
    cited rows resolve, not that a sentence follows from them.

    When this was written the fixture could not have cited its source at all: evidence is keyed by
    a runtime UUID. `T-207` changed that — the sentinel makes citing possible — and it does not
    change this test, because the excerpt these fixtures now cite says *"is described as"* and
    nothing about an announcement. A default fixture naming a provenance is still modelling an
    outbound sentence the system cannot support, which is the opposite of what a default is for. An
    adversarial one that does this deliberately belongs beside `T-057`'s injection corpus, named
    so a reader knows it is hostile on purpose.
    """
    offenders = [
        (name, word)
        for name, value in draft_personalizations()
        for word in INVENTED_PROVENANCE
        if word in value.lower()
    ]

    assert not offenders, (
        f"draft fixtures attributing a prospect fact to a source they cannot cite: {offenders}. "
        f"A fixture cannot carry an evidence id, so this models a claim the system cannot support."
    )


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


# --- T-136a: an approver is somebody -------------------------------------------------------------


def test_seeding_creates_the_approver_as_a_real_user(db_session: Session) -> None:
    """Criterion 1. Every seeded approval used to name a string that resolved to no row at all."""
    assert seed_approver(db_session) is None

    seed_synthetic(db_session, settings=TEST_SETTINGS)

    user = seed_approver(db_session)
    assert user is not None
    assert user.email == SEED_APPROVER
    assert user.active


def test_seeding_twice_does_not_create_a_second_approver(db_session: Session) -> None:
    seed_synthetic(db_session, settings=TEST_SETTINGS)
    seed_synthetic(db_session, settings=TEST_SETTINGS)

    assert (
        db_session.execute(
            select(func.count()).select_from(User).where(User.email == SEED_APPROVER)
        ).scalar_one()
        == 1
    )


def test_every_approver_the_seed_writes_resolves_to_a_user(db_session: Session) -> None:
    """Criterion 2, and the reason this task exists at all.

    Asked of the **database**, not of the constant: `T-136b` adds a foreign key over exactly these
    columns, and what it needs true is that no approver value anywhere in a seeded database is a
    string nobody can look up. Reading `SEED_APPROVER` back would prove only that the constant
    equals itself, and would keep passing if a writer were changed to record something else.
    """
    seed_synthetic(db_session, settings=TEST_SETTINGS)

    written = set(
        db_session.execute(select(ProductStatusVersion.approved_by)).scalars().all()
    ) | set(db_session.execute(select(ApprovedClaim.approved_by)).scalars().all())
    written |= set(db_session.execute(select(ApprovedClaimSet.approved_by)).scalars().all())
    written |= set(db_session.execute(select(CampaignPolicyVersion.approved_by)).scalars().all())
    assert written, "the seed recorded no approver at all, so this proves nothing"

    known = set(db_session.execute(select(User.email)).scalars().all())
    assert not (written - known), f"approver values with no user row: {sorted(written - known)}"


def test_the_shared_factory_names_an_approver_that_resolves_too(db_session: Session) -> None:
    """The same property for `World`, which is the other place approver values are written.

    Without this the factory half of `T-136a` would be untested: no foreign key exists yet, so a
    `World` that stopped creating its user would break nothing until `T-136b` — which is exactly
    the kind of gap that makes a later migration fail on somebody else's branch.
    """
    # `World` records audit events, and every consequential action needs a correlation id (§17.5).
    # Bound here rather than module-wide: the rest of this file is about the seeder, which the CLI
    # calls with its own.
    with structlog.contextvars.bound_contextvars(correlation_id="corr-fixture-factory-test"):
        world = World(db_session)
        approver = world.approval().approver_id

    written = set(db_session.execute(select(CampaignPolicyVersion.approved_by)).scalars().all()) | {
        approver
    }
    known = set(db_session.execute(select(User.email)).scalars().all())

    assert written, "the factory recorded no approver at all, so this proves nothing"
    assert not (written - known), f"approver values with no user row: {sorted(written - known)}"


def test_the_seeded_approver_is_unmistakably_synthetic(db_session: Session) -> None:
    """Criterion 3. AGENTS.md rule 1: an IANA-reserved domain that can never be delivered to."""
    seed_synthetic(db_session, settings=TEST_SETTINGS)
    user = seed_approver(db_session)

    assert user is not None
    assert user.email.endswith("@example.invalid")
    assert "synthetic" in user.email.lower()
    assert user.display_name.startswith(SYNTHETIC_PREFIX)


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


# --- T-189: the fixture router's couplings, which are literals in two files ----------------------


def test_every_seeded_campaign_has_a_draft_fixture_set() -> None:
    """`T-189` criterion 1. A campaign the router does not know raises `NoFixtureSetForPrompt`
    **during drafting** — inside a job, surfacing as a dead job's reason, which is the exact
    failure mode `T-172` was filed for."""
    unrouted = sorted(
        fixture.campaign_name
        for fixture in CAMPAIGN_FIXTURES
        if fixture.campaign_name not in DRAFT_OUTPUTS_BY_CAMPAIGN_NAME
    )

    assert not unrouted, f"seeded campaigns with no draft fixture set: {unrouted}"


def test_every_draft_fixture_set_names_a_seeded_campaign() -> None:
    """`T-189` criterion 2, the other direction. A key matching no campaign is either a typo that
    will never fire or a fixture set for a campaign somebody removed."""
    seeded = {fixture.campaign_name for fixture in CAMPAIGN_FIXTURES}
    orphaned = sorted(name for name in DRAFT_OUTPUTS_BY_CAMPAIGN_NAME if name not in seeded)

    assert not orphaned, f"draft fixture sets naming no seeded campaign: {orphaned}"


def test_the_draft_prompt_carries_the_marker_the_router_looks_for() -> None:
    """`T-189` criterion 3, and the coupling with the quietest failure.

    The router reads the marker out of the *rendered prompt*. Reword the template's first line and
    every draft routes to the qualification fixture set instead — no exception, just a §10.4-shaped
    answer to the wrong question, caught downstream by schema validation for a reason that names
    nothing about routing.
    """
    assert DRAFT_PROMPT_MARKER in prompt_template("draft")


def test_the_qualification_prompt_does_not_carry_the_draft_marker() -> None:
    """The same coupling from the other side: a qualification prompt that matched would route to a
    draft fixture set, and `FakeModelAdapter` would answer a qualification with a message."""
    assert DRAFT_PROMPT_MARKER not in prompt_template("qualification")


@pytest.mark.parametrize(
    "directory",
    [QUALIFICATION_OUTPUTS, *DRAFT_OUTPUTS_BY_CAMPAIGN_NAME.values()],
    ids=lambda path: path.name,
)
def test_every_routed_fixture_directory_exists(directory: Path) -> None:
    """`T-189` criterion 4. Referenced by path and, until now, never asserted to be there."""
    assert directory.is_dir(), f"the router points at {directory}, which does not exist"


def test_a_draft_prompt_naming_no_seeded_campaign_is_refused() -> None:
    """The refusal `T-172a` introduced and nothing exercised.

    It raises rather than falling back to the qualification set, because a draft answered from the
    wrong fixture set is a schema-valid message citing another campaign's approved claims — and
    §11.4 pins claims to the campaign for exactly that reason.
    """
    with pytest.raises(NoFixtureSetForPrompt):
        TaskRoutingFake().complete(
            prompt=f"{DRAFT_PROMPT_MARKER} for SYNTHETIC-Campaign-That-Was-Never-Seeded",
            parameters={},
        )


# --- T-207: a static fixture can cite evidence it cannot name -------------------------------------
#
# Evidence is keyed by a runtime UUID, so a file written in advance cannot name one. Once an
# uncited prospect statement became a validation failure, that left the fake model unable to
# produce a valid personalized draft at all — so the fixture cites a sentinel and the router
# substitutes the ids from the prompt it was given.


def test_the_sentinel_resolves_to_the_prompts_own_evidence_ids() -> None:
    first = "11111111-1111-4111-8111-111111111111"
    second = "22222222-2222-4222-8222-222222222222"
    prompt = f"{first}: SYNTHETIC excerpt one\n{second}: SYNTHETIC excerpt two"

    resolved = resolve_evidence_sentinels(
        json.dumps({"evidence_ids": ["SYNTHETIC-EVIDENCE-2"]}), prompt
    )

    assert json.loads(resolved)["evidence_ids"] == [second]


def test_a_sentinel_with_no_matching_evidence_resolves_to_nothing() -> None:
    """Not an error, and the reason is `T-207`'s own rule: a candidate nobody found evidence for
    should produce a draft that cannot be approved, which a reviewer then sees on `/attention`.
    Raising here would dead-letter the job instead, and a dead job is the failure nobody reads."""
    resolved = resolve_evidence_sentinels(
        json.dumps({"evidence_ids": ["SYNTHETIC-EVIDENCE-1"]}), "no evidence in this prompt"
    )

    assert json.loads(resolved)["evidence_ids"] == []


def test_output_without_a_sentinel_is_returned_unchanged() -> None:
    """Every qualification fixture and every draft that cites a real id goes through this path."""
    original = json.dumps({"evidence_ids": ["33333333-3333-4333-8333-333333333333"]})

    assert resolve_evidence_sentinels(original, "irrelevant prompt") == original


def test_the_substitution_never_reaches_the_drafting_module() -> None:
    """`resolve_citations` must keep raising on a citation it was not given — that is what catches
    a real model inventing an id. The sentinel is a development-only spelling, so it is resolved
    in the fixtures package and `drafting.py` never learns about it."""
    drafting = (
        Path(__file__).resolve().parents[1] / "app" / "drafts_and_approvals" / "drafting.py"
    ).read_text(encoding="utf-8")

    assert SENTINEL_PREFIX not in drafting


@pytest.mark.parametrize(
    "directory", list(DRAFT_OUTPUTS_BY_CAMPAIGN_NAME.values()), ids=lambda path: path.name
)
def test_every_draft_fixture_that_personalizes_cites_evidence(directory: Path) -> None:
    """The fixtures' own compliance with the rule. A default fixture that personalized without
    citing would put every candidate's draft straight into `validation_failed` — which is what
    both of them did before `T-207`."""
    for path in directory.glob("*.json"):
        fixture = json.loads(path.read_text(encoding="utf-8"))
        output = fixture.get("output")
        if not isinstance(output, dict) or not output.get("personalization", "").strip():
            continue
        assert output.get("evidence_ids"), f"{path.name} personalizes and cites no evidence"


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
        "/api/operations/flags/{key}",
        "/api/operations/overview",
        "/api/review/approvals/{approval_id}/revoke",
        "/api/review/attention/approvals",
        "/api/review/attention/revisions",
        "/api/review/candidates",
        "/api/review/candidates/{candidate_id}",
        "/api/review/candidates/{candidate_id}/approve",
        "/api/review/candidates/{candidate_id}/defer",
        "/api/review/candidates/{candidate_id}/reject",
        "/api/review/candidates/{candidate_id}/request-research",
        "/api/review/revisions",
        "/api/review/revisions/{revision_id}/approve",
        "/api/review/revisions/{revision_id}/edit",
        "/api/review/revisions/{revision_id}/refuse",
        "/healthz",
        "/readyz",
    ]
