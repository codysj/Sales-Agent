"""Synthetic development fixtures (specification §19.6 Stage 0/1, §24 item 4, GP-06).

Not a domain module. This package holds the deliberately fake world the backend is developed
and demonstrated against, so no real Matrix Power product brief, roadmap date, certification,
customer, or price is ever needed to run anything (`Q-017`, `Q-021`, `Q-022` are all still open).

Owns: fixture data and the seeders that load it. Must not own: any rule the production path
depends on. Nothing in `app/` outside this package may import it — a code path that needs a
fixture to work is a code path that would break on real data.
"""

from pathlib import Path

#: The T-041 prospect corpus. A path rather than a parsed object: the CSV is deliberately the
#: artifact, so the T-042 importer reads it the same way it will read an operator's file.
PROSPECTS_CSV = Path(__file__).resolve().parent / "prospects.csv"
