# Development-loop prompt

Usage: `/loop 30m` with the prompt below. This file is the durable copy; the protocol it points
at lives in `process.md` and `AGENTS.md` — this prompt deliberately restates none of it (`T-191`
is what happened last time a third copy existed).

---

Execute one iteration of this repository's development loop.

PROTOCOL — read `process.md` and `AGENTS.md` in full and follow them exactly. They own preflight,
implementation rules, verification layers, ledger updates, safety rules, and git policy. Read
`tasks.md` only by targeted query (its §3 preflight tells you how — header table, candidate task
block, §5 gate, §6 questions). This prompt adds nothing to the protocol except the report format
and the loop-cadence rules below.

TASK SELECTION
1. If a previous iteration left work unfinished — a task `IN_PROGRESS`, or verification still
   running in the background — resume and finish it. Never start a second task beside it.
2. Otherwise select per process.md §3.6 (the header's next-recommended `READY` task unless
   preflight shows it is no longer valid — say why if so).
3. One bounded task per iteration. Finishing early is a correct outcome; do not chain a second
   task to fill time.

CADENCE RULES (the only thing this prompt owns besides the report)
- The full backend suite takes ~1 hour and this loop fires every ~30 minutes. Run targeted tests
  synchronously; when a task needs the full canonical gate (backend code, schema, or workflow
  logic touched), start it in the background and collect the result in the same or the next
  iteration. A task is never `DONE` on a suite you did not observe finish — park it with a
  "Remaining work: full-suite result" line instead.
- If the database is unreachable (Docker down), verification cannot run: per process.md §5 the
  task is `PARTIAL`/`BLOCKED`, not `DONE`. Report it and stop — do not install anything, do not
  mock the database, do not mark anything done.
- Documentation-only tasks verify with the doc-reading tests
  (`uv run pytest -q tests/test_ledger_header.py tests/test_adr_index.py
  tests/test_specification_integrity.py tests/test_reconciliation.py`) plus any test the touched
  file names.
- Keep `tasks.md` machine-parseable: `#### T-###` headings, `- **Status:**` lines, §9 rows under
  200 characters. Tests read these formats; breaking them is a red suite, not a style choice.

GIT — no commit, push, branch, or PR. Uncommitted work accumulating is the checkpoint's known M1
condition: when completed-but-uncommitted paths exceed roughly 20, file or update a `BLOCKED`
task asking the user for a commit, as `T-194` did. The commit itself is always the user's.

STOP AND ASK — a gate unlock, a `Q-###` answer, a specification edit, an ADR acceptance the user
has not given, any external write, or anything process.md §2 calls an architecture change. File
it, mark it `BLOCKED`, report it. Never resolve it yourself.

REPORT (process.md §10 delegates the format to this prompt — use exactly this):

```text
LOOP_RESULT:      COMPLETED | PARTIAL | BLOCKED | IDLE | FAILED
TASK:             T-### — <objective in one line>
CHANGES:          <files and what changed; "none" if none>
VERIFICATION:     <commands run and their actual observed results — never described, only observed>
LEDGER:           <status transitions, new task IDs, gate changes>
NEXT:             <next recommended READY task, or the exact unblock condition>
EXTERNAL_ACTIONS: none
```

`EXTERNAL_ACTIONS` reads `none` unless the user explicitly authorized an external write in the
current session — in which case list each one performed.
