"""Fail-closed configuration defaults (T-003; specification §17.6, §19.6).

The point of these tests is that no missing, partial, or mistyped environment can hand the
application permission to reach the outside world.
"""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import REPO_ROOT, AppEnv, ModelProvider, Settings

SAFETY_VARS = ("APP_ENV", "DATABASE_URL", "SHADOW_MODE", "OUTBOUND_EMAIL_ENABLED", "MODEL_PROVIDER")
ENV_EXAMPLE = REPO_ROOT / ".env.example"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Observe declared defaults rather than the developer's own environment."""
    for var in SAFETY_VARS:
        monkeypatch.delenv(var, raising=False)


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        values[key.strip()] = value.strip()
    return values


def test_declared_defaults_are_fail_closed(clean_env: None) -> None:
    settings = Settings(_env_file=None)

    assert settings.shadow_mode is True
    assert settings.outbound_email_enabled is False
    assert settings.model_provider is ModelProvider.FAKE
    assert settings.app_env is AppEnv.LOCAL


def test_env_example_ships_fail_closed_values() -> None:
    """The committed template must never carry a value that enables an external effect."""
    values = _parse_env_file(ENV_EXAMPLE)

    assert values["SHADOW_MODE"] == "true"
    assert values["OUTBOUND_EMAIL_ENABLED"] == "false"
    assert values["MODEL_PROVIDER"] == "fake"
    assert values["APP_ENV"] == "local"


def test_env_example_documents_every_setting(clean_env: None) -> None:
    """A new setting must be added to the template, not left for a developer to discover."""
    documented = set(_parse_env_file(ENV_EXAMPLE))
    declared = {name.upper() for name in Settings(_env_file=None).model_dump()}

    assert declared <= documented, f"undocumented in .env.example: {sorted(declared - documented)}"


def test_env_example_contains_no_real_looking_credential() -> None:
    """Guard against a real key being pasted into the committed template."""
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    for pattern in (r"sk-[A-Za-z0-9]{16,}", r"AKIA[0-9A-Z]{16}", r"gh[pous]_[A-Za-z0-9]{20,}"):
        assert not re.search(pattern, text), f"possible credential matching {pattern!r}"


def test_unknown_model_provider_is_rejected(clean_env: None) -> None:
    """A real provider cannot be selected until it is added to ModelProvider (T-050, G-03)."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, model_provider="some-real-provider")  # type: ignore[arg-type]


def test_env_file_can_override_when_present(clean_env: None, tmp_path: Path) -> None:
    """Configuration is environment-driven, so the safe defaults are defaults and not a lock."""
    env_file = tmp_path / ".env"
    env_file.write_text("APP_ENV=test\nSHADOW_MODE=true\n", encoding="utf-8")

    settings = Settings(_env_file=env_file)

    assert settings.app_env is AppEnv.TEST
    assert settings.shadow_mode is True
