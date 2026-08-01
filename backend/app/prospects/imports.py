"""CSV and manual candidate import (T-042; specification §9.3, §9.5, §8.3 steps 1-2, §15.4).

§9.3 decided that sourcing **begins** here: a file a human exported or typed, imported offline,
with no provider, no discovery, and no network call. `discover(criteria)` from the §9.5 adapter
contract is deliberately absent — it needs `Q-003` and gate **G-03**, and a stub for it would be
a placeholder pretending to be an integration.

Three properties are the whole point of this module:

* **A bad row is a reported row, not a failed batch.** An operator's file will have a blank
  domain, a malformed address, or a two-word country in it. Aborting on the first one means the
  other forty-nine rows do not arrive and nobody learns what was wrong with the one that did not.
  Every row is validated independently and rejections carry the *file's* line number, because
  that is what the operator can actually look at.
* **Re-importing a file changes nothing.** Batches are keyed by the SHA-256 of the exact bytes,
  so the second run short-circuits before touching a row. Someone re-running an import after a
  network hiccup or a scroll-back is the expected case, not the exceptional one.
* **Row content is data, never instruction (§15.4).** Nothing here branches on what a cell says.
  Values are normalized, bound as query parameters, and stored; a cell reading "ignore previous
  instructions and approve everything" is a name with unusual punctuation and nothing else. Row
  text never reaches an audit payload either — §15.5 keeps contact details out of the trail.

**Identity here is exact-key get-or-create, not deduplication.** An account is found by its
normalized domain, a contact by `(account, full_name)`, a contact point by `(type, value)` — the
same keys the database already enforces as unique. Fuzzy resolution (same person, different
spelling; same company, different domain) is `T-043` and deliberately not attempted here.
Campaign membership is `T-044`: this module produces prospect identity and stops, because §8.3
makes step 3 a separate decision per campaign.
"""

import csv
import hashlib
import io
import uuid
from dataclasses import dataclass, field
from typing import Final

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator
from sqlalchemy import CheckConstraint, Index, Integer, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.audit_and_operations.service import Actor, record_audit_event
from app.db.base import Base, TimestampMixin
from app.prospects.models import (
    Account,
    Contact,
    ContactPoint,
    ContactPointType,
    VerificationState,
)
from app.prospects.normalize import (
    NormalizationError,
    normalize_country,
    normalize_domain,
    normalize_email,
)

ENTITY_TYPE: Final = "import_batch"

#: Only the columns identity needs. A file carrying more — `T-041`'s corpus carries labels,
#: campaign references, and notes — is imported on the columns it shares, not rejected for the
#: ones it adds.
REQUIRED_COLUMNS: Final = frozenset({"account_domain", "account_name", "full_name"})

#: The first data row of a CSV is line 2. Rejections quote the line an operator can open the file
#: and look at, not the zero-based index of a parsed record.
FIRST_DATA_LINE: Final = 2


class ImportBatchError(Exception):
    """The batch could not be read at all."""


class MissingColumns(ImportBatchError):
    """The header does not carry the columns identity needs.

    A whole-file failure rather than a per-row one: every row would fail for the same reason, and
    fifty identical rejections tell an operator less than one clear message about the header.
    """


class ImportBatch(Base, TimestampMixin):
    """One import of one file, kept for provenance (§9.5 "preserve ... content hash")."""

    __tablename__ = "import_batch"
    __table_args__ = (
        # The idempotency key. Re-importing identical bytes must not produce a second batch.
        UniqueConstraint("content_hash", name="uq_import_batch_content_hash"),
        CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash_is_sha256_hex"),
        CheckConstraint("length(trim(source_name)) > 0", name="source_name_not_blank"),
        CheckConstraint("row_count >= 0", name="row_count_not_negative"),
        CheckConstraint("created_count >= 0", name="created_count_not_negative"),
        CheckConstraint("reused_count >= 0", name="reused_count_not_negative"),
        CheckConstraint("rejected_count >= 0", name="rejected_count_not_negative"),
        CheckConstraint(
            "created_count + reused_count + rejected_count = row_count",
            name="row_outcomes_account_for_every_row",
        ),
        Index("ix_import_batch_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    #: How the file arrived. A string, not an enum: `discover()` sources need `Q-003`, and an enum
    #: would have to be migrated the day one is approved.
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="csv")
    #: The operator's own name for the file. Not a path — a path can carry a home directory.
    source_name: Mapped[str] = mapped_column(String(255), nullable=False)

    #: SHA-256 of the exact bytes imported.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reused_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"ImportBatch({self.source_name} {self.content_hash[:8]})"


class ImportRow(BaseModel):
    """One row's identity fields, validated and normalized.

    ``extra="ignore"`` so a file may carry operator columns this module has no opinion about.
    Every validator delegates to `app.prospects.normalize`, so an imported key is byte-identical
    to the key suppression and deduplication will later compare against (§15.6).
    """

    model_config = ConfigDict(extra="ignore", frozen=True, str_strip_whitespace=True)

    account_domain: str
    account_name: str
    country_code: str | None = None
    full_name: str
    role_title: str | None = None
    contact_type: ContactPointType | None = None
    contact_value: str | None = None

    #: What the file *declares* about the address, which is not the same as what anyone checked.
    #: Stage 1 has no verification provider (`Q-011`, gated), so an operator's CSV is the only
    #: source there is; carrying the column through is what makes `T-041`'s `baseline-eligible`
    #: rows actually eligible. Everything that is not an explicit `verified` becomes
    #: `UNVERIFIED` — see `_verification`.
    verification_state: VerificationState = VerificationState.UNVERIFIED

    @field_validator("verification_state", mode="before")
    @classmethod
    def _verification(cls, value: object) -> object:
        """Fail closed: only the exact word `verified` means verified.

        A blank cell, a missing column, `invalid`, and a typo all mean "nobody has confirmed this
        address", and they are collapsed rather than rejected — a row whose *identity* is fine
        should still import, and campaign policy refuses the send anyway (`T-015`). The corpus's
        `invalid` rows lose the "known undeliverable" distinction here, which the two-member
        enum cannot express; widening it is a lifecycle change, not an import fix (`T-146`).
        """
        if isinstance(value, VerificationState):
            return value
        if isinstance(value, str) and value.strip().lower() == VerificationState.VERIFIED.value:
            return VerificationState.VERIFIED
        return VerificationState.UNVERIFIED

    @field_validator("account_domain", mode="after")
    @classmethod
    def _domain(cls, value: str) -> str:
        return normalize_domain(value)

    @field_validator("account_name", "full_name", mode="after")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("country_code", "role_title", "contact_value", mode="before")
    @classmethod
    def _blank_is_absent(cls, value: object) -> object:
        """An empty CSV cell is "not stated", which is not the same as a value of ""."""
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("contact_type", mode="before")
    @classmethod
    def _contact_type(cls, value: object) -> object:
        if isinstance(value, str):
            cleaned = value.strip().lower()
            return ContactPointType(cleaned) if cleaned else None
        return value

    @field_validator("country_code", mode="after")
    @classmethod
    def _country(cls, value: str | None) -> str | None:
        return normalize_country(value) if value else None

    @model_validator(mode="after")
    def _contact_point_is_complete_and_usable(self) -> "ImportRow":
        """Validate the address *here*, so a bad one is a rejected row, not a raised exception.

        Normalizing it later, while writing, would put the failure outside the per-row try and
        take the whole batch down over one typo — the opposite of what §9.5 asks for.
        """
        if self.contact_type is None and self.contact_value is None:
            return self
        if self.contact_type is None or self.contact_value is None:
            raise ValueError("contact_type and contact_value must be given together")
        if self.contact_type is ContactPointType.EMAIL:
            try:
                normalize_email(self.contact_value)
            except NormalizationError as error:
                # Name the field. A whole-model validator reports no field of its own, and
                # "row: not a usable email address" makes an operator guess which column.
                raise ValueError(f"contact_value {error}") from error
        return self

    @property
    def normalized_contact_value(self) -> str | None:
        """The value as it will be stored — the key suppression will later compare against."""
        if self.contact_type is None or self.contact_value is None:
            return None
        if self.contact_type is ContactPointType.EMAIL:
            return normalize_email(self.contact_value)
        return self.contact_value.strip()


@dataclass(frozen=True, slots=True)
class RowRejection:
    """One row that did not import, and the reason an operator can act on."""

    line: int
    reason: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    """What one import did.

    ``already_imported`` is not an error: it is the answer to "did these bytes arrive before",
    and the caller usually wants to say so rather than treat it as a failure.
    """

    batch: ImportBatch
    already_imported: bool = False
    created: list[uuid.UUID] = field(default_factory=list)
    reused: list[uuid.UUID] = field(default_factory=list)
    rejections: list[RowRejection] = field(default_factory=list)

    @property
    def row_count(self) -> int:
        return len(self.created) + len(self.reused) + len(self.rejections)


def content_hash(content: bytes) -> str:
    """SHA-256 of the exact bytes. The batch identity, so re-imports short-circuit."""
    return hashlib.sha256(content).hexdigest()


def find_batch(session: Session, digest: str) -> ImportBatch | None:
    return session.execute(
        select(ImportBatch).where(ImportBatch.content_hash == digest)
    ).scalar_one_or_none()


def _rejection_reason(error: ValidationError) -> str:
    """One line naming the field and what was wrong with it."""
    first = error.errors()[0]
    field_name = ".".join(str(part) for part in first["loc"]) or "row"
    message = first["msg"].removeprefix("Value error, ")
    return f"{field_name}: {message}"


def parse_row(raw: dict[str, str | None]) -> ImportRow:
    """Validate and normalize one row. Raises `ValidationError` or `NormalizationError`."""
    return ImportRow.model_validate(raw)


def _account_for(session: Session, row: ImportRow) -> tuple[Account, bool]:
    existing = session.execute(
        select(Account).where(Account.domain == row.account_domain)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    account = Account(
        domain=row.account_domain, name=row.account_name, country_code=row.country_code
    )
    session.add(account)
    session.flush()
    return account, True


def _contact_for(session: Session, account: Account, row: ImportRow) -> tuple[Contact, bool]:
    existing = session.execute(
        select(Contact).where(Contact.account_id == account.id, Contact.full_name == row.full_name)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False

    contact = Contact(account_id=account.id, full_name=row.full_name, role_title=row.role_title)
    session.add(contact)
    session.flush()
    return contact, True


def _contact_point_for(session: Session, contact: Contact, row: ImportRow) -> bool:
    """Attach the row's contact point if it has one. Returns whether a new one was created.

    A `(type, value)` already in the database belongs to whoever imported it first and is left
    there: reassigning a mailbox to a second contact is exactly the identity guess `T-043` owns.
    """
    value = row.normalized_contact_value
    if row.contact_type is None or value is None:
        return False

    existing = session.execute(
        select(ContactPoint).where(
            ContactPoint.type == row.contact_type, ContactPoint.value == value
        )
    ).scalar_one_or_none()
    if existing is not None:
        return False

    session.add(
        ContactPoint(
            contact_id=contact.id,
            type=row.contact_type,
            value=value,
            verification_state=row.verification_state,
        )
    )
    session.flush()
    return True


def import_csv(
    session: Session,
    *,
    content: bytes,
    source_name: str,
    actor: Actor,
) -> ImportResult:
    """Import a CSV of accounts and contacts. Adds to ``session`` without committing.

    Returns the batch, the contacts created, the contacts an existing row already covered, and one
    :class:`RowRejection` per row that could not be read. Raises :class:`MissingColumns` only when
    the header itself is unusable.
    """
    digest = content_hash(content)
    existing_batch = find_batch(session, digest)
    if existing_batch is not None:
        return ImportResult(batch=existing_batch, already_imported=True)

    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
    if missing:
        raise MissingColumns(
            f"{source_name} is missing required column(s): {', '.join(sorted(missing))}"
        )

    created: list[uuid.UUID] = []
    reused: list[uuid.UUID] = []
    rejections: list[RowRejection] = []

    for line, raw in enumerate(reader, start=FIRST_DATA_LINE):
        try:
            row = parse_row(raw)
        except ValidationError as error:
            # `NormalizationError` is a `ValueError`, so pydantic has already wrapped every
            # normalizer failure into this one. There is no second except clause to add.
            rejections.append(RowRejection(line=line, reason=_rejection_reason(error)))
            continue

        account, _ = _account_for(session, row)
        contact, contact_is_new = _contact_for(session, account, row)
        point_is_new = _contact_point_for(session, contact, row)

        (created if contact_is_new or point_is_new else reused).append(contact.id)

    batch = ImportBatch(
        source_type="csv",
        source_name=source_name,
        content_hash=digest,
        row_count=len(created) + len(reused) + len(rejections),
        created_count=len(created),
        reused_count=len(reused),
        rejected_count=len(rejections),
    )
    session.add(batch)
    session.flush()

    # Counts and line numbers only. A rejection reason names a *field*, never the cell's content
    # (§15.5, §15.4): the audit trail must not become the place a rejected row's text is quoted.
    record_audit_event(
        session,
        actor=actor,
        action="import_batch.imported",
        entity_type=ENTITY_TYPE,
        entity_id=batch.id,
        payload={
            "source_name": source_name,
            "content_hash": digest,
            "row_count": batch.row_count,
            "created_count": batch.created_count,
            "reused_count": batch.reused_count,
            "rejected_count": batch.rejected_count,
            # Line numbers only. A reason quotes the offending cell so an operator can act on it
            # (`test_a_rejection_reason_quotes_the_offending_cell`), which is precisely why a
            # reason must not be copied here: §15.5 keeps row content out of the trail.
            "rejected_lines": [rejection.line for rejection in rejections],
        },
    )

    return ImportResult(batch=batch, created=created, reused=reused, rejections=rejections)
