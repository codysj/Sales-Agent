"""Operational kill switches (T-033; §17.6, §17.1).

Every test here is about a switch failing *closed*. The interesting cases are not "does the switch
work" but "can the switch be bypassed" — by a second configuration layer, by a subclass that forgot
to check, or by a pause that loses the work it stopped.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import structlog
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit_and_operations.flags import (
    ConsequentialWorkPaused,
    ExternalEffectBlocked,
    FlagError,
    FlagKey,
    GuardedAdapter,
    OperationalFlag,
    assert_consequential_work_allowed,
    consequential_work_allowed,
    is_set,
    outbound_email_allowed,
    set_flag,
    shadow_mode_active,
)
from app.audit_and_operations.models import ActorType, AuditEvent
from app.audit_and_operations.service import Actor
from app.core.lifecycles import JobState
from app.core.settings import Settings
from app.jobs_and_outbox.models import Job
from app.jobs_and_outbox.queue import enqueue, lease_jobs
from app.jobs_and_outbox.registry import JobRegistry
from app.jobs_and_outbox.retry import RetryPolicy
from app.jobs_and_outbox.runner import execute, run_once

OPERATOR = Actor(type=ActorType.HUMAN, id="operator-1")
POLICY = RetryPolicy(max_attempts=3, base_delay=timedelta(seconds=1), jitter=0.0)


class NoOpPayload(BaseModel):
    label: str


@pytest.fixture(autouse=True)
def _correlation() -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(correlation_id="corr-flags-test")


def unlocked_settings(**overrides: object) -> Settings:
    """Settings with the deploy-time switches *off*, to isolate the flag under test.

    Most tests here need shadow mode out of the way to prove that some *other* switch is doing the
    blocking. That the shipped defaults are the safe ones is asserted separately.
    """
    base: dict[str, object] = {"shadow_mode": False, "outbound_email_enabled": True}
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


# --- shipped defaults (criterion 1) ----------------------------------------------------------


def test_the_shipped_defaults_are_the_safe_ones(db_session: Session) -> None:
    """Criterion 1: shadow mode ON, outbound email OFF, with no flag rows at all."""
    settings = Settings()

    assert settings.shadow_mode is True
    assert settings.outbound_email_enabled is False
    assert shadow_mode_active(db_session, settings) is True
    assert outbound_email_allowed(db_session, settings) is False


def test_a_campaign_is_not_live_by_default() -> None:
    """The third default in criterion 1. Owned by `Campaign.paused` (T-015), not by a flag."""
    from app.campaigns.models import Campaign

    assert Campaign.paused.default is not None
    assert Campaign.paused.default.arg is True


def test_an_unset_flag_reads_as_off(db_session: Session) -> None:
    assert is_set(db_session, FlagKey.GLOBAL_PAUSE) is False


# --- setting flags is audited (criterion 3) --------------------------------------------------


def test_setting_a_flag_writes_an_audit_event_with_the_actor(db_session: Session) -> None:
    flag = set_flag(
        db_session,
        key=FlagKey.GLOBAL_PAUSE,
        enabled=True,
        actor=OPERATOR,
        reason="suspected bad claim data",
    )
    db_session.flush()

    audit = db_session.execute(
        select(AuditEvent).where(AuditEvent.entity_id == str(flag.id))
    ).scalar_one()
    assert audit.action == "flag.enabled"
    assert audit.actor_id == OPERATOR.id
    assert audit.payload["reason"] == "suspected bad claim data"


def test_releasing_a_flag_is_audited_too(db_session: Session) -> None:
    """Turning a pause *off* is the more consequential direction, so it is recorded the same way."""
    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    flag = set_flag(
        db_session,
        key=FlagKey.GLOBAL_PAUSE,
        enabled=False,
        actor=OPERATOR,
        reason="incident resolved, data corrected",
    )
    db_session.flush()

    actions = (
        db_session.execute(select(AuditEvent.action).where(AuditEvent.entity_id == str(flag.id)))
        .scalars()
        .all()
    )
    assert sorted(actions) == ["flag.disabled", "flag.enabled"]


def test_a_flag_change_without_a_reason_is_refused(db_session: Session) -> None:
    """A switch nobody can explain is a switch nobody dares turn off."""
    with pytest.raises(FlagError, match="needs a reason"):
        set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="   ")


def test_the_database_also_refuses_a_blank_reason(db_session: Session) -> None:
    db_session.add(
        OperationalFlag(
            key=FlagKey.GLOBAL_PAUSE,
            scope_id=None,
            enabled=True,
            reason="  ",
            set_by="operator-1",
            set_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError, match="flag_reason_not_blank"):
        db_session.flush()


def test_setting_the_same_flag_twice_updates_it_rather_than_duplicating(
    db_session: Session,
) -> None:
    """Two rows answering the same question is how a released pause stays in force."""
    first = set_flag(
        db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="one"
    )
    second = set_flag(
        db_session, key=FlagKey.GLOBAL_PAUSE, enabled=False, actor=OPERATOR, reason="two"
    )
    db_session.flush()

    assert first.id == second.id
    assert db_session.query(OperationalFlag).count() == 1
    assert is_set(db_session, FlagKey.GLOBAL_PAUSE) is False


def raw_flag(key: FlagKey, scope_id: str | None = None) -> OperationalFlag:
    return OperationalFlag(
        key=key,
        scope_id=scope_id,
        enabled=True,
        reason="synthetic",
        set_by="operator-1",
        set_at=datetime.now(UTC),
    )


def test_the_database_refuses_two_rows_for_one_global_key(db_session: Session) -> None:
    """`NULLS NOT DISTINCT`, and it matters.

    `set_flag` reads before writing, so it never reaches this constraint on its own — which is
    exactly why the constraint has to exist. Two operators throwing the same switch at the same
    moment would otherwise both insert, leaving two rows that disagree about whether the pause is
    on, and `is_set` would then fail on `scalar_one_or_none`. PostgreSQL's default treats every
    NULL scope as distinct, so without `NULLS NOT DISTINCT` this is allowed.
    """
    db_session.add(raw_flag(FlagKey.GLOBAL_PAUSE))
    db_session.flush()
    db_session.add(raw_flag(FlagKey.GLOBAL_PAUSE))

    with pytest.raises(IntegrityError, match="uq_operational_flag_key_scope"):
        db_session.flush()


def test_the_database_refuses_two_rows_for_one_scoped_key(db_session: Session) -> None:
    db_session.add(raw_flag(FlagKey.PRODUCT_DISABLED, "product-a"))
    db_session.flush()
    db_session.add(raw_flag(FlagKey.PRODUCT_DISABLED, "product-a"))

    with pytest.raises(IntegrityError, match="uq_operational_flag_key_scope"):
        db_session.flush()


def test_the_database_refuses_a_scope_on_a_global_key(db_session: Session) -> None:
    """The Python check in `set_flag` is not the only thing holding this."""
    db_session.add(raw_flag(FlagKey.GLOBAL_PAUSE, "product-a"))

    with pytest.raises(IntegrityError, match="scoped_keys_need_a_scope"):
        db_session.flush()


def test_the_database_refuses_a_scoped_key_without_a_scope(db_session: Session) -> None:
    db_session.add(raw_flag(FlagKey.PRODUCT_DISABLED, None))

    with pytest.raises(IntegrityError, match="scoped_keys_need_a_scope"):
        db_session.flush()


def test_a_scoped_key_requires_a_scope(db_session: Session) -> None:
    with pytest.raises(FlagError, match="needs a scope_id"):
        set_flag(db_session, key=FlagKey.PRODUCT_DISABLED, enabled=True, actor=OPERATOR, reason="x")


def test_a_global_key_refuses_a_scope(db_session: Session) -> None:
    with pytest.raises(FlagError, match="takes no scope_id"):
        set_flag(
            db_session,
            key=FlagKey.GLOBAL_PAUSE,
            enabled=True,
            actor=OPERATOR,
            reason="x",
            scope_id="some-product",
        )


def test_scoped_flags_are_independent(db_session: Session) -> None:
    set_flag(
        db_session,
        key=FlagKey.PRODUCT_DISABLED,
        enabled=True,
        actor=OPERATOR,
        reason="claims under review",
        scope_id="product-a",
    )
    db_session.flush()

    assert is_set(db_session, FlagKey.PRODUCT_DISABLED, scope_id="product-a") is True
    assert is_set(db_session, FlagKey.PRODUCT_DISABLED, scope_id="product-b") is False


# --- the two layers compose fail-closed ------------------------------------------------------


def test_the_flag_can_turn_shadow_mode_on_when_the_environment_has_it_off(
    db_session: Session,
) -> None:
    settings = unlocked_settings()
    assert shadow_mode_active(db_session, settings) is False

    set_flag(db_session, key=FlagKey.SHADOW_MODE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    assert shadow_mode_active(db_session, settings) is True


def test_the_flag_cannot_turn_shadow_mode_off_when_the_environment_has_it_on(
    db_session: Session,
) -> None:
    """The point of the conjunction: neither layer can weaken the other."""
    settings = Settings(shadow_mode=True)

    set_flag(
        db_session,
        key=FlagKey.SHADOW_MODE,
        enabled=False,
        actor=OPERATOR,
        reason="attempting to disable",
    )
    db_session.flush()

    assert shadow_mode_active(db_session, settings) is True


@pytest.mark.parametrize(
    "blocker",
    [FlagKey.OUTBOUND_EMAIL_DISABLED, FlagKey.SHADOW_MODE, FlagKey.GLOBAL_PAUSE],
)
def test_any_single_switch_stops_outbound_email(db_session: Session, blocker: FlagKey) -> None:
    settings = unlocked_settings()
    assert outbound_email_allowed(db_session, settings) is True

    set_flag(db_session, key=blocker, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    assert outbound_email_allowed(db_session, settings) is False


def test_email_needs_the_environment_to_agree_too(db_session: Session) -> None:
    settings = unlocked_settings(outbound_email_enabled=False)

    assert outbound_email_allowed(db_session, settings) is False


# --- the checkpoint ---------------------------------------------------------------------------


def test_global_pause_blocks_consequential_work(db_session: Session) -> None:
    assert consequential_work_allowed(db_session) is True

    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    assert consequential_work_allowed(db_session) is False
    with pytest.raises(ConsequentialWorkPaused):
        assert_consequential_work_allowed(db_session)


def test_a_paused_campaign_blocks_consequential_work(db_session: Session) -> None:
    """`Campaign.paused` is passed in, because `audit_and_operations` may not import `campaigns`."""
    assert consequential_work_allowed(db_session, campaign_paused=True) is False


# --- shadow mode is enforced at the adapter boundary (criterion 4) ---------------------------


class RecordingAdapter(GuardedAdapter[str, str]):
    """A synthetic adapter. It implements `_perform`, never `perform` — that is the guarantee."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def _perform(self, session: Session, request: str) -> str:
        self.calls.append(request)
        return "performed"


class RecordingEmailAdapter(RecordingAdapter):
    is_email = True


def test_an_adapter_acts_when_every_switch_permits_it(db_session: Session) -> None:
    adapter = RecordingAdapter()

    assert adapter.perform(db_session, unlocked_settings(), "synthetic") == "performed"
    assert adapter.calls == ["synthetic"]


def test_shadow_mode_blocks_the_adapter_before_it_acts(db_session: Session) -> None:
    """Criterion 4: the switch is checked in the base class, not at the call site."""
    adapter = RecordingAdapter()

    with pytest.raises(ExternalEffectBlocked, match="shadow mode"):
        adapter.perform(db_session, Settings(shadow_mode=True), "synthetic")

    assert adapter.calls == [], "the adapter must not have been reached at all"


def test_a_subclass_cannot_skip_the_check_by_forgetting_it(db_session: Session) -> None:
    """The structural half of criterion 4.

    `RecordingAdapter` contains no reference to any flag. It is blocked anyway, because the entry
    point belongs to the base class. A convention that every adapter must remember to call a guard
    is the convention that gets forgotten in the adapter written during an incident.
    """
    source = RecordingAdapter._perform.__code__.co_names

    assert not any("shadow" in name or "flag" in name.lower() for name in source)
    with pytest.raises(ExternalEffectBlocked):
        RecordingAdapter().perform(db_session, Settings(shadow_mode=True), "synthetic")


def test_a_global_pause_blocks_the_adapter(db_session: Session) -> None:
    adapter = RecordingAdapter()
    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    with pytest.raises(ConsequentialWorkPaused):
        adapter.perform(db_session, unlocked_settings(), "synthetic")

    assert adapter.calls == []


def test_the_email_switch_blocks_only_email_adapters(db_session: Session) -> None:
    set_flag(
        db_session,
        key=FlagKey.OUTBOUND_EMAIL_DISABLED,
        enabled=True,
        actor=OPERATOR,
        reason="deliverability check",
    )
    db_session.flush()
    settings = unlocked_settings()

    with pytest.raises(ExternalEffectBlocked, match="outbound email"):
        RecordingEmailAdapter().perform(db_session, settings, "synthetic")

    assert RecordingAdapter().perform(db_session, settings, "synthetic") == "performed"


# --- a pause loses no work (criterion 2) ------------------------------------------------------


def paused_registry() -> JobRegistry:
    registry = JobRegistry()
    registry.register(
        "synthetic.consequential",
        NoOpPayload,
        lambda s, p, *, job_id: None,
        retry_policy=POLICY,
        consequential=True,
    )
    registry.register(
        "synthetic.internal",
        NoOpPayload,
        lambda s, p, *, job_id: None,
        retry_policy=POLICY,
        consequential=False,
    )
    return registry


def test_consequential_declaration_is_required_at_registration() -> None:
    """Guessing what a global pause covers is the guess an operator cannot afford."""
    registry = JobRegistry()

    with pytest.raises(TypeError, match="consequential"):
        registry.register(  # type: ignore[call-arg]
            "synthetic.undeclared",
            NoOpPayload,
            lambda s, p, *, job_id: None,
            retry_policy=POLICY,
        )


def test_the_registry_lists_what_a_pause_must_stop() -> None:
    assert paused_registry().consequential_names() == ["synthetic.consequential"]


def test_a_pause_stops_consequential_jobs_without_losing_them(db_session: Session) -> None:
    """Criterion 2: none execute, none are lost, all stay inspectable."""
    registry = paused_registry()
    for job_type in ("synthetic.consequential", "synthetic.internal"):
        enqueue(
            db_session,
            job_type=job_type,
            payload={"label": "SYNTHETIC"},
            actor=OPERATOR,
            registry=registry,
        )
    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    ran = run_once(db_session, worker_id="worker-a", limit=10, registry=registry)

    assert ran == 1, "only the non-consequential job should have run"

    blocked = db_session.execute(
        select(Job).where(Job.job_type == "synthetic.consequential")
    ).scalar_one()
    assert blocked.state is JobState.QUEUED, "still visible and runnable, not dead or leased"
    assert blocked.attempt_count == 0, "a pause must not spend the job's attempt budget"
    assert blocked.last_error is None


def test_releasing_the_pause_lets_the_held_job_run(db_session: Session) -> None:
    """The other half of "none are lost": the work is still there afterwards."""
    registry = paused_registry()
    enqueue(
        db_session,
        job_type="synthetic.consequential",
        payload={"label": "SYNTHETIC"},
        actor=OPERATOR,
        registry=registry,
    )
    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()
    assert run_once(db_session, worker_id="worker-a", limit=10, registry=registry) == 0

    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=False, actor=OPERATOR, reason="resolved")
    db_session.flush()

    assert run_once(db_session, worker_id="worker-a", limit=10, registry=registry) == 1
    job = db_session.execute(
        select(Job).where(Job.job_type == "synthetic.consequential")
    ).scalar_one()
    assert job.state is JobState.SUCCEEDED


def test_a_paused_job_leased_some_other_way_is_still_refused(db_session: Session) -> None:
    """Defence in depth, for a pause thrown between the lease and the run."""
    registry = paused_registry()
    enqueue(
        db_session,
        job_type="synthetic.consequential",
        payload={"label": "SYNTHETIC"},
        actor=OPERATOR,
        registry=registry,
    )
    db_session.flush()
    job = lease_jobs(db_session, worker_id="worker-a", limit=1)[0]

    set_flag(db_session, key=FlagKey.GLOBAL_PAUSE, enabled=True, actor=OPERATOR, reason="incident")
    db_session.flush()

    with pytest.raises(ConsequentialWorkPaused):
        execute(db_session, job, registry=registry)

    assert isinstance(job.id, uuid.UUID)
