"""Developer command line (task T-040).

The third entry point beside `main.py` and `worker.py`, and the only one that loads fixtures.
Kept a leaf that nothing imports — like `worker.py`, it composes, so it is allowed to reach
across module boundaries that domain code may not.

Every command here is local-development only. Nothing in this file may send, deploy, mutate an
external system, or read a credential; `seed_synthetic` refuses to run outside a seedable
environment (`app/fixtures/synthetic.py`).
"""

import argparse
import logging
import sys
from collections.abc import Sequence

import structlog
from sqlalchemy.orm import Session

from app.core.logging import configure_logging
from app.core.settings import get_settings
from app.db.session import dispose_engines, get_engine
from app.fixtures.synthetic import SeedRefused, seed_synthetic

log = structlog.get_logger(__name__)

#: Exit code for a refused command. Distinct from 1 so a script can tell "not allowed here" from
#: "it broke".
EXIT_REFUSED = 2


def _seed_synthetic() -> int:
    settings = get_settings()
    engine = get_engine(settings.database_url)
    try:
        with Session(engine) as session:
            result = seed_synthetic(session, settings=settings)
            session.commit()
    except SeedRefused as refusal:
        log.error("cli.seed_synthetic.refused", reason=str(refusal))
        return EXIT_REFUSED
    finally:
        dispose_engines()

    log.info(
        "cli.seed_synthetic.done",
        app_env=settings.app_env.value,
        created=list(result.created),
        was_noop=result.was_noop,
    )
    return 0


COMMANDS = {"seed_synthetic": _seed_synthetic}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Local development commands. No external effects.",
    )
    parser.add_subparsers(dest="command", required=True).add_parser(
        "seed_synthetic",
        help="Load the synthetic campaign world (local and test environments only).",
    )
    arguments = parser.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.app_env, level=logging.INFO)
    return COMMANDS[arguments.command]()


if __name__ == "__main__":
    sys.exit(main())
