"""Typed campaign policy (specification §8.1, §8.6, §10.1, ADR-012).

The policy body is stored as JSONB but is never *read* as loose JSON: it round-trips through
this Pydantic model, so a policy that has drifted from the current shape fails loudly at load
rather than silently granting or denying eligibility later.

Every default here is the conservative one. A policy that omits a field must not accidentally
widen geography, raise a volume cap, or relax readiness.
"""

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.products_and_claims.models import ReadinessCategory

#: §15.8 and §19.6 Stage 6: the first live pilot is U.S.-only until Matrix Power confirms
#: other jurisdictions (`Q-013`).
DEFAULT_ALLOWED_COUNTRIES = ("US",)

#: `Q-014` has not set expected volume, so the defaults are deliberately small. §19.6 Stage 6
#: describes the micro-pilot as roughly five individually approved sends per day.
DEFAULT_DAILY_SEND_CAP = 5
DEFAULT_TOTAL_SEND_CAP = 50


class SuppressionScope(BaseModel):
    """Which suppression scopes this campaign honours (§15.6).

    All default to on. Suppression is stronger than campaign configuration, so a policy may
    widen what it respects but the send-time check never consults this to *skip* a scope.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    person: bool = True
    email: bool = True
    domain: bool = True
    account: bool = True


class CampaignPolicy(BaseModel):
    """The versioned rules a campaign evaluates candidates against.

    Hard eligibility (§10.1 stage 1) reads this. Nothing here is advisory: a model
    recommendation cannot overturn a value in this object (T-045).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: ISO 3166-1 alpha-2. Empty means *nothing is allowed*, not "anywhere" — fail closed.
    allowed_countries: tuple[str, ...] = DEFAULT_ALLOWED_COUNTRIES

    #: Readiness a product must hold for this campaign to reference it (§2.3, GP-12).
    #: Defaults exclude `sellable_now` deliberately: until `Q-021`/`Q-022` deliver approved
    #: briefs, no product may be positioned as generally available.
    required_readiness: tuple[ReadinessCategory, ...] = (
        ReadinessCategory.EVALUATION_OR_PILOT,
        ReadinessCategory.IN_DEVELOPMENT,
        ReadinessCategory.STRATEGIC_OR_ROADMAP,
    )

    #: Normalized account domains this campaign never contacts (§10.1 hard rules).
    excluded_domains: tuple[str, ...] = ()
    #: Free-text exclusion reasons an operator has approved, e.g. an industry or company type.
    excluded_segments: tuple[str, ...] = ()

    daily_send_cap: int = Field(default=DEFAULT_DAILY_SEND_CAP, ge=0)
    total_send_cap: int = Field(default=DEFAULT_TOTAL_SEND_CAP, ge=0)

    suppression_scope: SuppressionScope = SuppressionScope()

    #: A contact must have a verified address before a send is considered (§15.8).
    require_verified_email: bool = True

    @field_validator("allowed_countries", mode="after")
    @classmethod
    def _uppercase_country_codes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(code.strip().upper() for code in value)

    @field_validator("excluded_domains", mode="after")
    @classmethod
    def _normalize_domains(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(domain.strip().lower().removeprefix("www.") for domain in value)

    def permits_country(self, country_code: str | None) -> bool:
        """Unknown geography is refused, not assumed domestic."""
        if not country_code:
            return False
        return country_code.strip().upper() in self.allowed_countries

    def permits_readiness(self, readiness: ReadinessCategory) -> bool:
        return readiness in self.required_readiness

    def excludes_domain(self, domain: str | None) -> bool:
        if not domain:
            return False
        return domain.strip().lower().removeprefix("www.") in self.excluded_domains
