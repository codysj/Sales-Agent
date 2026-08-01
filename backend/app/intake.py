"""Turning an import into campaign membership work (T-169; §8.3 steps 1-2, §9.3, §14.2).

**The step that was missing.** `prospects.import_csv` creates accounts, contacts, and contact
points and stops — deliberately, because §8.3 makes membership `campaigns`' business and
`ImportRow` ignores the CSV's `campaigns` column on purpose. Nothing then picked it up. The code
that did lived in `tests/test_shadow_slice.py`, so the pipeline was proven end to end in a
transaction nobody kept, while a real database finished an import with zero candidates and a
worker with nothing to do.

**This is not a job, and that is the same reasoning `campaigns/jobs.py` records for the import.**
An operator uploading a CSV is a request: it commits, and the membership work it implies is
enqueued in front of them rather than in a queue they would have to go looking for.

**It sits at the top level, beside `job_types.py`, and the boundary checker put it there.** The
obvious home was `campaigns` — membership is its business — but `prospects` already imports
`campaigns`, so a `campaigns` module importing `prospects` closes a package cycle and
`tests/test_module_boundaries.py::test_no_import_cycles` refuses it. What this actually is, is a
**composition**: it knows that a prospect row names campaigns, which is knowledge neither package
has alone, so it belongs where `job_types.py` already lives — outside both, imported by the
entry points that compose them.

**One job per (row, campaign), not per row.** A row naming two campaigns produces two candidates,
and §8.1 makes those judgements independent — sharing one correlation ID would put two independent
histories on one trail. Every job in a candidate's chain inherits the ID from the job that enqueued
it, so a prospect's whole history stays one `WHERE correlation_id = ?` (§3.5, §17.5).
"""

import csv
import io
import uuid
from typing import Final

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit_and_operations.service import Actor
from app.campaigns.jobs import MEMBERSHIP_JOB_TYPE
from app.jobs_and_outbox.queue import enqueue
from app.prospects.imports import parse_row
from app.prospects.models import Account, Contact

log = structlog.get_logger(__name__)

#: The column naming the campaigns a row should join, and its separator. Read here rather than in
#: `ImportRow` because membership is this package's business (§8.3).
CAMPAIGNS_COLUMN: Final = "campaigns"
CAMPAIGN_SEPARATOR: Final = "|"


def campaign_slugs_by_row(content: bytes) -> list[tuple[dict[str, str | None], list[str]]]:
    """Each raw CSV row paired with the campaign slugs it names.

    A row naming no campaign yields an empty list and is skipped by the caller: joining every
    campaign by default is exactly the "automated CRM creation for every discovered candidate"
    §9.3 says not to begin with.
    """
    text = content.decode("utf-8-sig")
    rows: list[tuple[dict[str, str | None], list[str]]] = []
    for raw in csv.DictReader(io.StringIO(text)):
        named = raw.get(CAMPAIGNS_COLUMN) or ""
        slugs = [slug.strip() for slug in named.split(CAMPAIGN_SEPARATOR) if slug.strip()]
        rows.append((raw, slugs))
    return rows


def enqueue_memberships_for_import(
    session: Session,
    *,
    content: bytes,
    batch_id: uuid.UUID,
    actor: Actor,
) -> int:
    """Enqueue one membership job per (row, campaign). Returns how many were enqueued.

    Adds without committing, so the caller's transaction decides — the same contract
    `import_csv` and `seed_synthetic` keep.

    A row whose account or contact the import did not create is skipped rather than guessed at:
    it was rejected for a reason the import already reported, and inventing an identity here would
    put a candidate behind a row a human refused.

    **A row naming no campaign joins none**, and there is no guard for it: the per-slug loop has
    nothing to iterate. An earlier `if not slugs: continue` was deleted after a negative control
    proved it changed nothing — a check that cannot fail reads as protection while providing none.
    The behaviour is pinned by `test_a_row_naming_no_campaign_enqueues_nothing`, because it is the
    behaviour that matters: joining every campaign by default is the "automated CRM creation for
    every discovered candidate" §9.3 says not to begin with.
    """
    enqueued = 0
    for index, (raw, slugs) in enumerate(campaign_slugs_by_row(content)):
        try:
            row = parse_row(raw)
        except Exception:
            # Already counted and explained by `import_csv`'s rejections; re-reporting it here
            # would double the count an operator sees.
            continue

        account = session.execute(
            select(Account).where(Account.domain == row.account_domain)
        ).scalar_one_or_none()
        if account is None:
            continue
        contact = session.execute(
            select(Contact).where(
                Contact.account_id == account.id, Contact.full_name == row.full_name
            )
        ).scalar_one_or_none()

        for slug in slugs:
            enqueue(
                session,
                job_type=MEMBERSHIP_JOB_TYPE,
                payload={
                    "account_id": str(account.id),
                    "contact_id": str(contact.id) if contact else None,
                    "campaign_slugs": [slug],
                },
                actor=actor,
                # Per candidate, and traceable back to the import that produced it.
                correlation_id=f"import-{batch_id.hex[:12]}-{index}-{slug}",
            )
            enqueued += 1

    log.info("campaigns.memberships_enqueued", batch_id=str(batch_id), jobs=enqueued)
    return enqueued
