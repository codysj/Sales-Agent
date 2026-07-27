"""Structured logging.

Every line is JSON and carries the correlation ID bound by
:class:`app.core.middleware.RequestContextMiddleware`, so a request, the jobs it enqueues,
and the audit events it writes can be joined after the fact (specification §17.5).

Log content is subject to §15.5: never log a contact, prompt, email body, token, or secret.
"""

import logging
import sys
from typing import TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from app import APP_VERSION
from app.core.settings import AppEnv


def _static_context(app_env: AppEnv) -> Processor:
    """Stamp every line with the versions §17.5 requires for correlation."""

    def processor(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
        event_dict.setdefault("app_version", APP_VERSION)
        event_dict.setdefault("app_env", app_env.value)
        return event_dict

    return processor


def configure_logging(
    app_env: AppEnv,
    *,
    stream: TextIO | None = None,
    level: int = logging.INFO,
) -> None:
    """Configure structlog process-wide.

    ``stream`` exists so tests can capture and parse real rendered output rather than
    trusting a mock. ``cache_logger_on_first_use`` stays off so a reconfiguration during a
    test run actually takes effect; the cost is irrelevant at pilot volume.
    """
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _static_context(app_env),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=stream or sys.stdout),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=False,
    )
