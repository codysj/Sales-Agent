# ADR-019 — Deduplication matches on address or name, never on role title

- **Status:** ACCEPTED (2026-07-30)
- **Scope:** Local to this repository. Does not modify any inherited specification ADR.
- **Specification basis:** §8.3 step 2 requires deduplication against internal records; §19.2 lists
  "campaign-membership uniqueness and deduplication" as a deterministic correctness test; §10.1
  keeps identity deterministic and §18.6 forbids the vector database a fuzzy matcher would want.
  None of them says which keys constitute a match. This ADR fills exactly that gap.
- **Implemented by:** `T-043` (`backend/app/prospects/dedup.py`).

## Decision

Two contacts are the same person only when one of these holds, checked in this order:

| Rule | Key | Recorded as |
|---|---|---|
| 1 | The same normalized email address | `MatchReason.EXACT_EMAIL` |
| 2 | The same account **and** the same normalized personal name | `MatchReason.DOMAIN_AND_NAME` |

Account-level deduplication is exact by construction: `Account.domain` is unique and normalized, so
`find_account(domain)` resolves an account with no heuristic.

**"Account domain + role title" is rejected as a contact-match rule.** `T-043`'s scope named it;
this ADR is the record of not implementing it.

Name normalization is case-folding and whitespace-collapsing only. Punctuation stripping,
`Last, First` reordering, nickname tables, and middle-name elision are all rejected.

## Why

**A role is not an identity.** Two people at one company routinely share a role title — "Operations
Manager", "Site Lead" — and matching on it would fold two distinct humans into one contact. The
failure is silent and it is not symmetric with the alternative: a missed duplicate leaves two
records an operator can merge later, while a wrong merge has already re-pointed evidence and
carried suppression onto the survivor.

**Merges are effectively irreversible.** `merge_contacts` moves contact points, re-points campaign
candidates, and re-records `PERSON`-scope suppressions against the surviving contact. Undoing that
by hand means reconstructing which of the survivor's records came from which original. The rule set
is therefore biased towards under-matching.

**Deterministic means readable, not merely reproducible.** Each rule is one comparison of two
normalized strings, and the match reason is recorded on the merge audit event, so a merge can be
explained months later without re-running anything.

## Rejected alternatives

- **Role-title matching** — merges distinct people, as above.
- **Similarity scoring or embeddings** — needs a threshold nobody can justify from evidence, and a
  vector database §18.6 rules out without a measured requirement.
- **Provider identity resolution** — `Q-003` has confirmed no enrichment provider; §9.3 begins with
  manual and CSV import.
- **Merging across accounts** — refused outright (`NotMergeable`). Two domains are two companies
  until someone decides otherwise, and that decision is not the importer's to make.

## What would make us revisit

- A measured duplicate rate that exact rules demonstrably miss, on the `T-080` labeled set rather
  than on impression.
- A schema that can express a role mailbox (`ops@`) as distinct from a named person, which would
  make a role-scoped rule safe because it would no longer be about people.
- CRM-side deduplication becoming available (`Q-001`, gate **G-05**), which brings its own identity
  keys and would need this record revisited alongside §13.5 rule 2.
