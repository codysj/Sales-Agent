"""The synthetic prospect corpus (T-041; specification §19.1, §15.9, GP-06).

`app/fixtures/prospects.csv` is the world the import, dedup, eligibility, and evidence tasks
(`T-042`…`T-046`) develop against, so two properties have to hold before any of them trust it:

* **Nothing in it can reach a real person.** Every address sits under an IANA reserved example
  domain (RFC 2606), every name carries the `SYNTHETIC` marker, and no cell carries a digit —
  the same blunt rule `test_fixtures.py` applies to the campaign world, and the reason a real
  phone number or street address cannot hide in a `note`.
* **Each labeled edge case actually exhibits its edge case.** A row labeled
  `duplicate-email-case` whose two addresses do not in fact normalize to one mailbox would let
  `T-043` pass while doing nothing, so the labels are checked against the T-016 normalizers
  rather than taken at face value.

These tests are pure: the corpus is a file, not a database, and nothing here needs PostgreSQL.
The §19.1 labeled *evaluation* set (30-50 prospects per campaign, eight label dimensions) is a
separate artifact and belongs to `T-080`.
"""

import csv
import re
from pathlib import Path

import pytest

from app.fixtures import PROSPECTS_CSV
from app.fixtures.synthetic import CAMPAIGN_FIXTURES
from app.prospects.normalize import (
    NormalizationError,
    normalize_country,
    normalize_domain,
    normalize_email,
)

#: RFC 2606 §3 reserved second-level domains. A subdomain of one is reserved too, so
#: `alpha.example.com` qualifies; anything else does not.
RESERVED_EXAMPLE_DOMAINS = ("example.com", "example.org", "example.net")

#: Criterion 2's seven cases. The corpus may carry more; it may never carry fewer.
REQUIRED_CASES = frozenset(
    {
        "duplicate-email-case",
        "duplicate-domain-name",
        "non-us-record",
        "suppressed-email",
        "missing-contact-point",
        "unverifiable-email",
        "both-campaigns",
    }
)

EXPECTED_COLUMNS = [
    "case_label",
    "account_domain",
    "account_name",
    "country_code",
    "full_name",
    "role_title",
    "contact_type",
    "contact_value",
    "verification_state",
    "campaigns",
    "note",
]


def rows() -> list[dict[str, str]]:
    with PROSPECTS_CSV.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def rows_labeled(case: str) -> list[dict[str, str]]:
    return [row for row in rows() if row["case_label"] == case]


def is_reserved_example_domain(domain: str) -> bool:
    return any(
        domain == reserved or domain.endswith(f".{reserved}")
        for reserved in RESERVED_EXAMPLE_DOMAINS
    )


# --- shape ---------------------------------------------------------------------------------


def test_the_corpus_parses_with_the_expected_columns() -> None:
    with PROSPECTS_CSV.open(encoding="utf-8", newline="") as handle:
        header = next(csv.reader(handle))

    assert header == EXPECTED_COLUMNS
    assert len(rows()) >= len(REQUIRED_CASES), "too few rows to cover the required cases"


def test_no_row_is_ragged() -> None:
    """An unquoted comma in a note silently shifts every column after it (`DictReader` parks the
    overflow under a `None` key), which reads as a corpus that parsed fine."""
    ragged = [
        (index, row)
        for index, row in enumerate(rows(), start=2)
        if None in row or any(value is None for value in row.values())
    ]

    assert not ragged, f"rows whose field count does not match the header: {ragged}"


def test_every_row_carries_a_case_label_and_a_note() -> None:
    """An unlabeled row is a row nobody can tell the purpose of six tasks from now."""
    unlabeled = [row for row in rows() if not row["case_label"].strip() or not row["note"].strip()]

    assert not unlabeled, f"rows without a label or a note: {unlabeled}"


# --- criterion 1: reserved example domains only --------------------------------------------


def test_every_email_domain_is_a_reserved_example_domain() -> None:
    offenders = [
        row["contact_value"]
        for row in rows()
        if row["contact_type"] == "email"
        and not is_reserved_example_domain(normalize_email(row["contact_value"]).rpartition("@")[2])
    ]

    assert not offenders, f"addresses outside RFC 2606 reserved domains: {offenders}"


def test_every_account_domain_is_a_reserved_example_domain() -> None:
    offenders = [
        row["account_domain"]
        for row in rows()
        if not is_reserved_example_domain(normalize_domain(row["account_domain"]))
    ]

    assert not offenders, f"account domains outside RFC 2606 reserved domains: {offenders}"


def test_the_reserved_domain_check_rejects_a_lookalike() -> None:
    """`notexample.com` ends in `example.com` as a string but is a different registration."""
    assert not is_reserved_example_domain("notexample.com")
    assert not is_reserved_example_domain("example.com.attacker.test")
    assert is_reserved_example_domain("alpha.example.com")


# --- criterion 3: nothing derived from a real organization or person ------------------------


def test_every_account_and_person_name_is_marked_synthetic() -> None:
    offenders = [
        value
        for row in rows()
        for value in (row["account_name"], row["full_name"], row["role_title"])
        if "synthetic" not in value.lower()
    ]

    assert not offenders, f"names that do not say SYNTHETIC: {offenders}"


def test_no_cell_contains_a_digit() -> None:
    """No digit means no real phone number, street address, headcount, or revenue figure."""
    offenders = [
        (row["case_label"], column, value)
        for row in rows()
        for column, value in row.items()
        # A ragged row parks its overflow in a list under a `None` key; that is
        # `test_no_row_is_ragged`'s failure to report, not this one's to crash on.
        if isinstance(value, str) and re.search(r"\d", value)
    ]

    assert not offenders, f"cells carrying digits: {offenders}"


def test_every_local_part_is_derived_from_its_synthetic_account() -> None:
    """A local part that does not come from the fake account is where a real name would hide."""
    offenders = [
        row["contact_value"]
        for row in rows()
        if row["contact_type"] == "email"
        and "person" not in normalize_email(row["contact_value"]).partition("@")[0]
    ]

    assert not offenders, f"addresses whose local part is not a synthetic person: {offenders}"


# --- criterion 2: the seven edge cases, each doing what its label claims --------------------


def test_every_required_edge_case_is_present() -> None:
    labels = {row["case_label"] for row in rows()}

    assert labels >= REQUIRED_CASES, f"missing edge cases: {sorted(REQUIRED_CASES - labels)}"


def test_duplicate_email_case_rows_normalize_to_one_mailbox() -> None:
    duplicates = rows_labeled("duplicate-email-case")

    assert len(duplicates) >= 2
    assert len({row["contact_value"] for row in duplicates}) > 1, "the rows are already identical"
    assert len({normalize_email(row["contact_value"]) for row in duplicates}) == 1


def test_duplicate_domain_name_rows_share_an_account_and_a_person_but_not_an_address() -> None:
    duplicates = rows_labeled("duplicate-domain-name")

    assert len(duplicates) >= 2
    assert len({normalize_domain(row["account_domain"]) for row in duplicates}) == 1
    assert len({row["full_name"] for row in duplicates}) == 1
    assert len({normalize_email(row["contact_value"]) for row in duplicates}) == len(duplicates)


def test_the_non_us_row_is_a_valid_country_that_is_not_us() -> None:
    countries = {normalize_country(row["country_code"]) for row in rows_labeled("non-us-record")}

    assert countries and "US" not in countries


def test_the_missing_contact_point_row_has_no_contact_point_at_all() -> None:
    incomplete = rows_labeled("missing-contact-point")

    assert incomplete
    assert all(not row["contact_type"] and not row["contact_value"] for row in incomplete)


def test_the_unverifiable_rows_cover_both_known_bad_and_never_checked() -> None:
    """`unverified` is not a weaker `invalid`: policy refuses both, for different reasons."""
    states = {row["verification_state"] for row in rows_labeled("unverifiable-email")}

    assert states == {"invalid", "unverified"}


def test_the_suppressed_row_would_otherwise_be_eligible() -> None:
    """A suppressed row that fails eligibility anyway proves nothing about suppression."""
    suppressed = rows_labeled("suppressed-email")

    assert suppressed
    assert all(
        row["verification_state"] == "verified" and row["country_code"] == "US"
        for row in suppressed
    )


def test_the_both_campaigns_rows_name_both_seeded_campaigns() -> None:
    seeded = {fixture.campaign_slug for fixture in CAMPAIGN_FIXTURES}
    shared = rows_labeled("both-campaigns")

    assert shared
    assert all(set(row["campaigns"].split("|")) == seeded for row in shared)
    assert len({normalize_domain(row["account_domain"]) for row in shared}) == 1


# --- the corpus must be importable ----------------------------------------------------------


def test_every_campaign_reference_matches_a_seeded_campaign() -> None:
    """A slug typo here would silently produce a corpus that belongs to no campaign."""
    seeded = {fixture.campaign_slug for fixture in CAMPAIGN_FIXTURES}
    referenced = {slug for row in rows() for slug in row["campaigns"].split("|")}

    assert referenced <= seeded, f"unknown campaign slugs: {sorted(referenced - seeded)}"


def test_every_identity_value_survives_normalization() -> None:
    """The T-016 normalizers are what `T-042` will run; nothing here may be unimportable."""
    failures: list[tuple[str, str]] = []
    for row in rows():
        for value, normalizer in (
            (row["account_domain"], normalize_domain),
            (row["country_code"], normalize_country),
            (row["contact_value"] if row["contact_type"] == "email" else "", normalize_email),
        ):
            if not value:
                continue
            try:
                normalizer(value)
            except NormalizationError as error:
                failures.append((value, str(error)))

    assert not failures, f"values the importer could not normalize: {failures}"


@pytest.mark.parametrize("column", ["contact_type", "verification_state"])
def test_enum_columns_use_known_values(column: str) -> None:
    allowed = {
        "contact_type": {"", "email", "phone", "linkedin_url"},
        "verification_state": {"", "unverified", "verified", "invalid"},
    }[column]
    values = {row[column] for row in rows()}

    assert values <= allowed, f"{column} carries unknown values: {sorted(values - allowed)}"


def test_the_corpus_lives_in_the_fixtures_package() -> None:
    assert PROSPECTS_CSV.is_file()
    assert PROSPECTS_CSV.parent.name == "fixtures"
    assert PROSPECTS_CSV.parent.parent.name == "app"
    assert isinstance(PROSPECTS_CSV, Path)
