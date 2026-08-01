"""FastAPI application factory.

The API process. It owns authorization, validation, policy decisions, immutable review
revisions, and task creation — never open-ended browsing and never background execution,
which belongs to the worker (specification §5.1).

Only liveness and readiness are exposed so far; domain routers arrive with their modules.
"""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Literal

import structlog
from fastapi import Depends, FastAPI, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app import APP_VERSION
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.settings import Settings, get_settings
from app.db.session import check_database, dispose_engines
from app.drafts_and_approvals.api import router as review_router
from app.identity.api import router as auth_router
from app.job_types import register_job_types
from app.outreach_and_replies.api import router as outreach_router

log = structlog.get_logger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]


class Liveness(BaseModel):
    status: Literal["ok"]
    version: str


class Readiness(BaseModel):
    status: Literal["ready", "not_ready"]
    database: Literal["ok", "unavailable"]
    shadow_mode: bool
    detail: str | None = None


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    log.info(
        "application.started",
        app_env=settings.app_env.value,
        shadow_mode=settings.shadow_mode,
        outbound_email_enabled=settings.outbound_email_enabled,
        model_provider=settings.model_provider.value,
    )
    try:
        yield
    finally:
        dispose_engines()
        log.info("application.stopped")


def create_app(*, configure_logs: bool = True) -> FastAPI:
    settings = get_settings()
    if configure_logs:
        configure_logging(settings.app_env, level=logging.INFO)

    app = FastAPI(
        title="Matrix Power Always-On AI Sales Agent",
        version=APP_VERSION,
        summary="Application-owned sales workflow. Shadow mode; live outreach is gated.",
        lifespan=lifespan,
    )
    # The API enqueues jobs — `T-058b2b2a`'s candidate approval queues drafting — and `enqueue`
    # resolves each job type's payload model from the registry to validate it. The worker calls
    # this in `main()` too; without the same call here, any endpoint that enqueues raises
    # `UnknownJobType` at runtime while every unit test of the same code path passes, because
    # the test registered the type itself. Found by `T-154a`, whose approve endpoint could not
    # work. Idempotent, so a process that is both API and worker is fine.
    register_job_types()

    app.add_middleware(RequestContextMiddleware)
    app.include_router(auth_router)
    app.include_router(review_router)
    app.include_router(outreach_router)

    @app.get("/healthz", response_model=Liveness, tags=["operations"])
    def healthz() -> Liveness:
        """Liveness. Deliberately touches no dependency, so it stays up while they are down."""
        return Liveness(status="ok", version=APP_VERSION)

    @app.get("/readyz", response_model=Readiness, tags=["operations"])
    def readyz(settings: SettingsDep, response: Response) -> Readiness:
        """Readiness. Fails closed: anything other than a successful round-trip is 503."""
        try:
            check_database(settings.database_url)
        except SQLAlchemyError as exc:
            log.warning("readiness.database_unavailable", error=type(exc).__name__)
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
            return Readiness(
                status="not_ready",
                database="unavailable",
                shadow_mode=settings.shadow_mode,
                # Type name only: a driver message can carry host and credential fragments.
                detail=type(exc).__name__,
            )

        return Readiness(status="ready", database="ok", shadow_mode=settings.shadow_mode)

    return app


app = create_app()
