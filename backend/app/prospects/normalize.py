"""Identity normalization (specification §8.3 step 2, §13.5, §15.6).

Deduplication and suppression are only as good as the keys they compare. ``Sales@Example.COM``
and ``sales@example.com`` are the same mailbox, and a suppression recorded against one must stop
a send to the other (§15.6) — so normalization happens on write, not at comparison time.

All input here is untrusted (§15.4): these functions are given CSV cells and provider fields, and
they normalize or reject rather than trusting the shape.
"""

import re

__all__ = [
    "NormalizationError",
    "normalize_country",
    "normalize_domain",
    "normalize_email",
    "normalize_person_name",
]

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*://")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_COUNTRY = re.compile(r"^[A-Z]{2}$")
_WHITESPACE = re.compile(r"\s+")


class NormalizationError(ValueError):
    """A value could not be normalized into a usable identity key."""


def normalize_domain(value: str) -> str:
    """Lowercase registrable host: no scheme, no ``www.``, no path, port, or trailing dot.

    ``https://WWW.Example.com/about?x=1`` and ``example.com.`` both give ``example.com``.
    """
    cleaned = value.strip().lower()
    if not cleaned:
        raise NormalizationError("domain must not be blank")

    cleaned = _SCHEME.sub("", cleaned)
    # Strip any userinfo, then cut at the first path, query, or fragment separator.
    cleaned = cleaned.rpartition("@")[2]
    for separator in ("/", "?", "#"):
        cleaned = cleaned.partition(separator)[0]
    cleaned = cleaned.partition(":")[0]  # port
    cleaned = cleaned.strip(".")
    cleaned = cleaned.removeprefix("www.")

    if not cleaned or "." not in cleaned or " " in cleaned:
        raise NormalizationError(f"{value!r} is not a usable domain")
    return cleaned


def normalize_email(value: str) -> str:
    """Lowercase, whitespace-stripped address.

    The local part is technically case-sensitive per RFC 5321, but every mailbox provider this
    system will encounter treats it case-insensitively. Lowercasing is what makes deduplication
    and suppression correct in practice; the alternative silently lets ``Sales@`` and ``sales@``
    become two contacts, one of them unsuppressed.

    Provider-specific tricks (Gmail dots, ``+`` tags) are deliberately **not** applied: they are
    wrong for other providers, and guessing that two addresses are the same person is worse than
    treating them as two.
    """
    cleaned = value.strip().lower()
    if not _EMAIL.match(cleaned):
        raise NormalizationError(f"{value!r} is not a usable email address")
    return cleaned


def normalize_person_name(value: str) -> str:
    """A comparison key for a person's name: lowercase, single-spaced, trimmed.

    A **comparison** key only — the stored name keeps the operator's own spelling (§14.1), so this
    is never written back. Deliberately conservative: case and runs of whitespace are the two
    differences that mean nothing, and nothing else is touched. Stripping punctuation, reordering
    "Last, First", or dropping middle names would each merge people who are not the same person,
    and a merge is the identity operation that cannot be undone by hand (T-043, ADR-019).

    Returns ``""`` for a blank name rather than raising: an empty key must never match another
    empty key into a merge, and the caller checks for it.
    """
    return _WHITESPACE.sub(" ", value.strip()).lower()


def normalize_country(value: str) -> str:
    """ISO 3166-1 alpha-2, uppercased.

    Format only — membership of the allowed set is campaign policy (`T-015`), not identity.
    """
    cleaned = value.strip().upper()
    if not _COUNTRY.match(cleaned):
        raise NormalizationError(
            f"{value!r} is not an ISO 3166-1 alpha-2 country code (two letters)"
        )
    return cleaned
