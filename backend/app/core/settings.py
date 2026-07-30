"""Application configuration.

Every switch that could produce an external effect defaults to the safe value, so a missing
or partial environment can never enable one by accident (specification §17.6 operational
controls, §19.6 rollout stages). Flipping one requires the matching stage gate in
``tasks.md`` §5 to be unlocked.

Provider names and endpoints live here in configuration, never in business logic
(specification §18.4).
"""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/settings.py -> backend/app -> backend -> repository root.
# Resolved from the file location so configuration loads identically regardless of the
# working directory the API, worker, or test run starts from.
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class AppEnv(StrEnum):
    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class ModelProvider(StrEnum):
    """Model providers the application is permitted to construct.

    Only the deterministic fake exists until gate G-03 (production-like model data use) is
    unlocked and Q-012 names an approved baseline provider and data-handling settings. Adding
    a member here is a deliberate, reviewable act — see task T-050.
    """

    FAKE = "fake"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # `model_provider` is configuration, not a Pydantic model attribute; the shadowing
        # check would otherwise reject the name that matches the MODEL_PROVIDER variable.
        protected_namespaces=(),
    )

    app_env: AppEnv = AppEnv.LOCAL
    # Host port 55432, matching docker-compose.yml: a native PostgreSQL on the developer's
    # machine commonly owns 5432, and connections would silently reach it instead of the
    # container. See docs/development.md.
    database_url: str = "postgresql+psycopg://matrix:localdev@localhost:55432/matrix_sales"

    # --- Fail-closed safety switches -------------------------------------------------
    # shadow_mode: when true, external-effect adapters refuse to act at all (enforced at
    # the adapter boundary by T-033/T-035, not at individual call sites).
    shadow_mode: bool = True
    outbound_email_enabled: bool = False
    model_provider: ModelProvider = ModelProvider.FAKE

    # Blank by default, and blank means *reject every webhook*, not "skip the check" (§19.4).
    # No provider secret is committed anywhere: `Q-004` has chosen no provider, and the tests
    # generate their own secret per run.
    webhook_signing_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings, read once.

    Cached so configuration cannot drift between a request and the job it enqueues. Tests
    that need different values should construct ``Settings`` directly rather than clearing
    this cache.
    """
    return Settings()
