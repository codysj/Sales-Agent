"""Which source adapter a job may construct (T-058b2a; §9.5, §15.3, §18.5, gate **G-06**).

A job handler's signature is `(session, payload, *, job_id)`. There is no argument through which
a caller can hand it a source adapter, so the payload names one and this resolves the name. That
is the same shape `model_gateway.registry.build_provider` uses for model providers, and for the
same reason: **one place to audit what can come into existence.**

**Empty by default, and that is the point.** `FixtureSourceAdapter` is the only Stage 1 adapter
and it reads a directory of synthetic documents under `app/fixtures/`, which `T-040` forbids any
production module to import — a code path that needs a fixture to work is a code path that would
break on real data. So nothing registers itself here. The CLI and the tests register the fixture
adapter with the directory they want, and production ships with a registry that resolves nothing
and refuses loudly.

That refusal is the useful behaviour, not an inconvenience: a `research.capture_evidence` job
queued in an environment where no adapter is registered fails with a message naming the gate,
rather than quietly capturing nothing and leaving a candidate that looks researched.

**A real adapter is a reviewable code change, not a configuration edit.** Registering a name is
one call, so the guard against a network source appearing is not this file — it is §15.3's
requirements (SSRF protection, redirect and size limits, isolated parsing), gate **G-06**, and
`Q-003` having chosen no provider. `tests/test_evidence_capture.py` asserts that nothing under
`research_and_evidence` imports an HTTP client, which is the check that actually bites.
"""

from collections.abc import Callable
from typing import Final

from app.research_and_evidence.adapters.protocol import SourceAdapter

#: Adapter factories by name. **Empty on purpose** and asserted empty by
#: `tests/test_pipeline_jobs.py`: no production module may register one, because the only
#: Stage 1 adapter needs a fixture directory to read.
SOURCE_ADAPTERS: Final[dict[str, Callable[[], SourceAdapter]]] = {}

#: The name the fixture adapter is conventionally registered under. Defined here so the CLI, the
#: tests, and a job payload all spell it the same way; registering it is still the caller's act.
FIXTURE_ADAPTER_NAME: Final = "fixture"


class SourceAdapterNotAvailable(Exception):
    """No adapter is registered under this name in this process."""


def register_source_adapter(name: str, factory: Callable[[], SourceAdapter]) -> None:
    """Make ``name`` resolvable. Called by the CLI or a test, never by a domain module.

    Re-registering the same name replaces the factory rather than raising, unlike the job
    registry: two workers registering one job type is a collision, but a caller supplying a
    different fixture directory for a different run is the ordinary case.
    """
    if not name.strip():
        raise ValueError("source adapter name must not be blank")
    SOURCE_ADAPTERS[name] = factory


def unregister_source_adapter(name: str) -> None:
    """Remove a registration. Exists so a test can restore the empty default it found."""
    SOURCE_ADAPTERS.pop(name, None)


def build_source_adapter(name: str) -> SourceAdapter:
    """The adapter registered under ``name``, or raise.

    The only way to obtain one, so there is a single place to audit.
    """
    factory = SOURCE_ADAPTERS.get(name)
    if factory is None:
        raise SourceAdapterNotAvailable(
            f"no source adapter registered under {name!r}; known: "
            f"{sorted(SOURCE_ADAPTERS) or '(none)'}. Stage 1 registers the fixture adapter from "
            f"the CLI or a test; a network source needs §15.3's controls and gate G-06 "
            f"(`Q-003` has chosen no provider)"
        )
    return factory()
