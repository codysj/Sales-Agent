"""Which model provider may be constructed (T-050; §18.4, ADR-017, gate **G-03**).

The rule this file exists to enforce: **no real provider client can come into existence while
gate G-03 is locked.** Two independent locks, because one is a single edit away from being
wrong:

1. `Settings.model_provider` must name a non-fake provider — and `ModelProvider` has exactly one
   member, so today there is nothing to name.
2. `Settings.allow_real_model_provider` must be true. It defaults to false, and adding an enum
   member does not change that.

Even with both, `REAL_PROVIDER_ADAPTERS` is empty, so construction still fails. That is the third
lock and the honest one: no real adapter has been written, reviewed, or approved. `Q-012` has not
named a provider or its data-handling terms, and §15.9 requires that review before any business
contact data reaches one.

`build_provider` is the only way to obtain an adapter, so there is a single place to audit.

**Which fake, though.** `EchoModelAdapter` needs no configuration, so it is the default and
stays the default. `T-052`'s `FakeModelAdapter` returns fixture-keyed output — what the pipeline
actually needs to produce §10.4-valid results — but it reads a directory under `app/fixtures/`,
which `T-040` forbids any production module to import. So the fake's *construction* is a hook
(`set_fake_adapter_factory`) that the CLI and tests install into, exactly as
`research_and_evidence.adapters.registry` handles source adapters (`T-058b2a`). The hook changes
which fake is built; it cannot make a real provider appear, because all three locks above sit on
the other branch. `build_provider` is still the only entry point, and still the only place to
audit.
"""

from collections.abc import Callable
from typing import Final

from app.core.settings import ModelProvider, Settings
from app.model_gateway.protocol import ModelProviderAdapter
from app.model_gateway.providers.echo import EchoModelAdapter


class ProviderNotPermitted(Exception):
    """A provider was requested that this build is not allowed to construct."""


#: Real providers, by enum member. **Empty on purpose** and asserted empty by
#: `tests/test_model_gateway.py`: gate **G-03** is locked and `Q-012` has chosen nothing.
REAL_PROVIDER_ADAPTERS: Final[dict[ModelProvider, type[ModelProviderAdapter]]] = {}

#: How the *fake* provider is constructed. The default needs no configuration and no fixtures, so
#: a process that installs nothing still works — and still cannot reach a network.
_DEFAULT_FAKE_FACTORY: Final[Callable[[], ModelProviderAdapter]] = EchoModelAdapter

_fake_factory: Callable[[], ModelProviderAdapter] = _DEFAULT_FAKE_FACTORY


def set_fake_adapter_factory(factory: Callable[[], ModelProviderAdapter]) -> None:
    """Install the fake adapter a process should build. Called by the CLI or a test.

    Not by a domain module: the only fixture-keyed fake reads `app/fixtures/`, and a production
    module that installed it would be a production module that needs fixtures to work.
    """
    global _fake_factory
    _fake_factory = factory


def reset_fake_adapter_factory() -> None:
    """Restore the echo default. Exists so a test can put back what it found."""
    global _fake_factory
    _fake_factory = _DEFAULT_FAKE_FACTORY


def build_provider(settings: Settings) -> ModelProviderAdapter:
    """The provider adapter this configuration permits, or raise.

    Returns the deterministic in-process adapter for `ModelProvider.FAKE`. `T-052` replaces that
    adapter's body with fixture-keyed outputs and deliberate failure modes; the resolution rules
    here do not change when it does.
    """
    # Compared by value, not identity, on purpose. `ModelProvider` has a single member today, so
    # an identity check lets mypy prove everything below is unreachable and delete-by-warning the
    # guard that has to be here the day a member is added.
    if settings.model_provider.value == ModelProvider.FAKE.value:
        return _fake_factory()

    if not settings.allow_real_model_provider:
        raise ProviderNotPermitted(
            f"provider {settings.model_provider!r} requires ALLOW_REAL_MODEL_PROVIDER; gate G-03 "
            f"is locked and `Q-012` has not approved a provider or its data-handling terms "
            f"(§15.9)"
        )

    adapter = REAL_PROVIDER_ADAPTERS.get(settings.model_provider)
    if adapter is None:
        raise ProviderNotPermitted(
            f"no adapter exists for provider {settings.model_provider!r}; a real client is a "
            f"reviewable code change, not a configuration edit (§18.4, ADR-017)"
        )
    return adapter()
