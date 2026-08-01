"""Model budgets (T-050; specification §18.7, GP-14).

§18.7 asks for "per-task, daily, and campaign budgets" and cost attribution. Three properties
make these budgets worth having:

* **They are checked before the provider is invoked, not after.** A budget enforced on the way
  out has already spent the money it was meant to protect.
* **They are deterministic.** The limit comes from configuration and the spend comes from a
  `SUM` over `model_run`. No model, no heuristic, no estimate.
* **They fail closed.** A limit of zero refuses everything, and a scope with no configured limit
  falls back to the conservative default rather than to "unlimited".

**Two units, and only one of them binds today.** A run records both a call count and a cost, and
both are capped. With `ModelProvider.FAKE` the only provider that exists, every run costs zero,
so the *call* caps are what actually stop a runaway loop in Stage 1. The cost caps are wired and
tested so they cannot be forgotten the day a real provider is approved — but the numbers in them
are placeholders, not a budget anyone has agreed: `Q-006` has not set pilot spend and `Q-012` has
not named a provider or its pricing. They are deliberately small, in the same spirit as
`CampaignPolicy`'s five-sends-a-day default.
"""

from decimal import Decimal
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

#: Calls one bounded task may make in a day. Small enough that a loop stops being cheap quickly.
DEFAULT_TASK_DAILY_CALLS: Final = 50
#: Calls across every task in a day.
DEFAULT_DAILY_CALLS: Final = 200
#: Calls attributable to one campaign in a day.
DEFAULT_CAMPAIGN_DAILY_CALLS: Final = 100

#: Placeholder money caps (`Q-006`, `Q-012`). Zero spend is possible today because the only
#: provider is the fake, so these bind nothing yet — they exist so the check is already in the
#: path when a real provider arrives, rather than being remembered later.
DEFAULT_DAILY_COST_USD: Final = Decimal("5.00")
DEFAULT_CAMPAIGN_DAILY_COST_USD: Final = Decimal("2.50")


class BudgetScope(BaseModel):
    """One limit pair. Both are ceilings; either one refuses on its own."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: int = Field(ge=0)
    max_cost_usd: Decimal = Field(ge=0)


class ModelBudgets(BaseModel):
    """The three §18.7 scopes.

    Every field has a conservative default, so a partially configured environment is restrictive
    rather than unlimited — the same rule every other policy object in this repository follows.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    #: Per bounded task, per day.
    per_task: BudgetScope = BudgetScope(
        max_calls=DEFAULT_TASK_DAILY_CALLS, max_cost_usd=DEFAULT_DAILY_COST_USD
    )
    #: All tasks, per day.
    daily: BudgetScope = BudgetScope(
        max_calls=DEFAULT_DAILY_CALLS, max_cost_usd=DEFAULT_DAILY_COST_USD
    )
    #: One campaign, per day.
    per_campaign: BudgetScope = BudgetScope(
        max_calls=DEFAULT_CAMPAIGN_DAILY_CALLS, max_cost_usd=DEFAULT_CAMPAIGN_DAILY_COST_USD
    )
