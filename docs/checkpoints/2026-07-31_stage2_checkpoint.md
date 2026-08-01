# Checkpoint Audit — 2026-07-31 — Stage 2 (Review Dashboard)

## 1. Audit date, baseline, scope, and limitations

| Field | Value |
|---|---|
| **Audit date** | 2026-07-31 |
| **Auditor** | Independent checkpoint pass (verification only; no application code modified) |
| **Baseline commit** | `62514a4904cc` ("Clarify invoking prompt ownership of loop report format") |
| **Working tree** | **118 uncommitted paths** (31 modified, 87 untracked) — effectively the entire Stage 1 and Stage 2 implementation lives only in the working tree. See finding **M1**. |
| **Prior checkpoint** | None. `docs/checkpoints/` did not exist before this report. |
| **Task range in scope** | All ledger work: 100 `DONE`, 5 `READY`, 7 `PLANNED`, 5 `BLOCKED`, 1 `SPLIT` at audit start. |
| **Specification** | `docs/MATRIX_POWER_ALWAYS_ON_SALES_AGENT_SPEC_v0.3.md` (SHA pinned in `AGENTS.md`). |

**Limitations.** With no prior checkpoint, the honest baseline is *everything*. One hundred `DONE`
tasks cannot each receive a line-by-line re-derivation in one pass. The method used instead:

- **Every automated check re-run by the auditor** — nothing below quotes a prior report's numbers.
- **Deep verification** of the highest-stakes surfaces: safety invariants, dispatch preconditions,
  shadow-mode enforcement, the approval transaction, authentication/RBAC, migration reversibility.
- **Traceability sampling** across 14 named suites covering the Stage 2 task chain end to end and
  the Stage 1 core (§7 below).
- **Adversarial reading** of the ledger against the code, hunting for `DONE` claims the code does
  not support — which produced findings H1, M2, L1–L3.

What this audit did **not** do: re-derive every Stage 1 task's acceptance criteria individually
(they are exercised collectively by the 2,050-test suite and the Stage 1 exit evidence document),
or execute the docker-compose reachability check (T-134's evidence is dated 2026-07-27 and was not
re-run; the test suite's live PostgreSQL connection on port 55432 demonstrates reachability today).

## 2. Executive verdict

**`PASS_WITH_ACTIONS`**

The implemented system matches the specified architecture, every safety invariant checked holds,
all 2,050 backend and 127 frontend tests pass under the auditor's own runs, and all 27 migrations
reverse and re-apply cleanly. No `STOP` finding. One `HIGH` finding (already self-reported by the
loop as T-157) must close before the stage gate; three `MEDIUM` and four `LOW` findings are
recorded with actions. The ledger was found accurate in substance with four small
status/prose inconsistencies, corrected in this pass.

## 3. Current stage and gate status

| Item | State |
|---|---|
| Stage | **Stage 2 — Review dashboard** (§19.6), entered 2026-07-31 |
| Stage exit gate | **G-10** — a non-engineer completes reviews without understanding the agent stack. **LOCKED**, correctly: T-068b, T-070 (CSRF), T-071 (walkthrough rehearsal), and now T-157 remain. |
| Gates open | G-01 (Stage 1 engineering), G-02 (Stage 2 dashboard work, opened 2026-07-31 on `docs/stage1-exit-evidence.md`) |
| Gates locked | G-03…G-10 — verified still locked in §5, and no `READY` task sits behind a locked gate. |

**Audit constraint recorded in the ledger:** G-10 must not be evaluated for closure while T-157 is
open (finding H1).

## 4. Work completed since baseline commit

The baseline commit predates nearly all implementation. In scope, materially:

- **Stage 1 (complete, G-02 open):** 13-module backend per §18.2; import → membership →
  eligibility → evidence → qualification → drafting → validation pipeline through a
  PostgreSQL-backed job queue with leases, retries, dead-lettering, recovery, and a transactional
  outbox; claims/evidence stores with fail-closed validity; model gateway with fake provider and
  budget enforcement; suppression; webhook intake (fail-closed on missing secret); 27 migrations.
- **Stage 2 (in progress):** identity (roles, sessions, RBAC matrix, local stub sign-in over HTTP);
  review queue + candidate detail APIs; Next.js dashboard (sign-in, review card, edit form,
  approve/reject/defer/request-research actions — all five §12.3 item 6 actions live); the §11.3
  approval transaction (steps 2–6) plus its step 1 endpoint; structured invalidation reasons,
  attention list, and revocation endpoint; ADR-018…ADR-022.

## 5. Independently verified (auditor's own runs)

| Check | Observed result |
|---|---|
| `uv run ruff check .` | All checks passed |
| `uv run ruff format --check .` | 196 files already formatted |
| `uv run mypy app` | Success: no issues in 108 source files |
| `uv run alembic check` | No new upgrade operations detected |
| `uv run pytest -q` | **2050 passed** (228.6 s) |
| `uv run alembic downgrade base` → `upgrade head` | **27 down / 27 up, clean**; `alembic check` clean after — full-chain reversibility, which per-cycle work had only ever tested one step at a time |
| `npm run lint` / `typecheck` / `build` (frontend) | Clean; build compiles, 4 routes |
| `npx vitest run` | **127 passed** across 7 files |
| Safety invariant suites (`test_invariants`, `test_module_boundaries`) | 45 passed |
| Credential scan (`app/`, `frontend/`) | No matches outside `SYNTHETIC-` fixtures |
| Live-effect scan (smtplib/sendgrid/hubspot/requests/httpx in `app/`) | No live client imports; only doc references |
| `.env.example` | Fail-closed values only (`SHADOW_MODE=true`, `OUTBOUND_EMAIL_ENABLED=false`, `MODEL_PROVIDER=fake`, blank webhook secret = reject-all); no secrets |
| Shadow-mode enforcement | Three independent layers verified in code: `build_effect_adapter` can only return the fake (no real adapter exists to construct); `GuardedAdapter.perform` raises `ExternalEffectBlocked` under `shadow_mode_active()` (settings **or** DB kill-flag); `outbound_email_allowed` as a second switch. `tests/netguard.py` patches `socket.socket.connect` — transport-level, below any SDK. |
| `npm audit` | `{high: 3, critical: 0}` — down from the 7 recorded in T-152 (tree drifted with later installs); task text stale, see M3 |

## 6. Not verified, and why

- **T-134** (docker compose container starts): not re-executed; the live test-suite database on
  port 55432 is the practical evidence it still holds.
- **Per-task re-derivation of all 100 `DONE` tasks:** sampled, not exhaustive (§1 limitations).
- **The §12.3 walkthrough by an actual non-engineer:** T-071's business, not an audit's.
- **Frontend flake history (T-150):** the fix (a measured 30 s timeout) was verified by the loop
  across 20 consecutive runs; this audit ran the suite 1× clean and did not repeat the 20-run
  campaign.

## 7. Acceptance-criteria traceability (sampled, deepest-risk first)

| Task | Claim | Auditor's evidence | Verdict |
|---|---|---|---|
| T-035/T-035b/c (dispatch) | §11.4 rechecks; ambiguous → `delivery_unknown`, never blind retry | `test_dispatch.py`, 70 tests incl. `test_timeout_and_ambiguous_acceptance_are_indistinguishable_downstream` asserting `not is_safe_to_retry` | **Supported** |
| T-055 (validation) | Nine fail-closed checks, migration-backed | `test_revision_validation.py` 34 tests; checks enumerated in `Check` enum; boilerplate templates split (T-156) without a test edit | **Supported** |
| T-021/T-068a (approval lifecycle) | §8.4 triggers detected with triggering record; revoked/expired/invalidated cannot dispatch | `test_approval.py` 24 + `test_approval_lifecycle.py` 31; `require_valid` raises at the precondition; two unreachable triggers documented as immutability-guarded, not untested | **Supported**, with H1 caveat on pins |
| T-067a/b (§11.3 transaction) | Atomic approval+command+outbox; recheck at approval time; no agent callback | `test_approval_transaction.py` 40, incl. savepoint-rollback atomicity proof and a transitive import walk that also detects package-level import evasion | **Supported**, §11.4 field completeness deferred to T-157 |
| T-061a/T-151a (sessions) | Hashed tokens, revocable, stub refused outside `local`, token never logged | `test_sessions.py` 34 + `test_session_api.py` 21, incl. log-capture scan and environment parametrization | **Supported** |
| T-062/T-063a (RBAC) | Every route declared; matrix-wide role×approval test; human-only approval roles | `test_authz.py` 40; route-coverage guard fails on undeclared routes (proven by this cycle's own controls) | **Supported** |
| T-065a (immutable edit) | Prior revision byte-identical; approvals retired; validation re-run | `test_review_edit.py` 23; DB trigger independently refuses content mutation | **Supported** |
| T-058c (Stage 1 exit) | End-to-end slice, zero external writes | `docs/stage1-exit-evidence.md` + `test_shadow_slice.py` 34 under socket guard | **Supported** |
| T-066a/b1/b2, T-153/155 (decisions) | §10.6 enum in migration; deferral waypoint constraints; research pass moves nothing | `test_corrections.py` 38 + `test_decision_api.py` 60 + `test_pipeline_jobs.py` 110 | **Supported** |
| T-137 (revocation entry point) | — | **Overlap found**: `revoke()` + endpoint + audit event now exist via T-021/T-068a; remaining delta is thin (see M2) | **READY is correct but scope shrank** |

## 8. Test and verification results

Totals: **2050 backend + 127 frontend, all passing under audit runs.** Zero xfail/skip markers
active (the two historical `xfail(strict=True)` markers from T-140/T-141 were resolved and removed;
comments documenting them remain). Test depth spot-checks found controls-driven suites that assert
failure paths, counts-either-side-of-refusal, and structural guards — not import-only tests. The
one systemic test-quality caveat: several suites were authored by the same loop that wrote the
code; this audit's independence rests on re-running them plus adversarial code reading, not on
authorship separation.

## 9. Architecture and safety-invariant checklist

| Invariant | Status | Evidence |
|---|---|---|
| Application owns orchestration/execution | ✅ | Worker + queue + outbox in `jobs_and_outbox`; no external orchestrator |
| OpenClaw/NemoClaw optional, off critical path | ✅ | Zero references in `app/` outside docs; T-067a structural test scans for `openclaw`/`nemoclaw` |
| Messaging complementary, not approval path | ✅ | No messaging adapter exists; gate G-04 locked |
| Product statements require approved claims | ✅ | `Check.CLAIM_CITATIONS` + `PRODUCT_STATEMENT_GROUNDING`, fail closed |
| Prospect assertions require evidence | ✅ | `Check.EVIDENCE_CITATIONS` |
| Approval binds an immutable revision | ✅ | `T-020` DB trigger + `approval_pins_immutable` trigger; audit-verified via test refusals |
| Suppression & approval checked at execution | ✅ / ⚠️ | Dispatch preconditions re-check both; **⚠️ H1**: null pins skip claim/status currency at dispatch |
| External integrations fake/disabled until gated | ✅ | `build_effect_adapter` returns fake unconditionally; shadow default true; email switch off |
| Five lifecycles separate | ✅ | `test_only_the_owning_package_names_a_lifecycle` + module-boundary suite (both actively caught violations during Stage 2 work) |
| No model-controlled approval | ✅ | Approval endpoints require human session (`APPROVE_*` granted to human-only roles; service identities structurally excluded three ways) |
| No premature infrastructure | ✅ | No Kafka/Redis/K8s/Temporal/vector DB in manifests |
| No credentials committed | ✅ | Scan clean; `.env` git-ignored; blank-secret-means-reject webhook posture |

## 10. Assumption register

| # | Assumption | Class | Evidence | Impact / becomes blocking |
|---|---|---|---|---|
| A1 | Spec v0.3 is approved for buildout | `CONFIRMED_DECISION` (header) / record gap tracked | Spec header; **no stored acceptance record** — R-002, T-009 `BLOCKED` | Blocking for formal Stage 0 closure narrative; not for synthetic development |
| A2 | Bearer-token-only mutations are an acceptable interim CSRF stance | `ENGINEERING_DEFAULT` | `requires_bearer` + module docstring; T-070 owns the real answer | Blocking at G-10 (T-070 is a gate dependency) |
| A3 | 8-hour session TTL, sessionStorage token, 55432 port, TS 5.9, 30 s drift-test timeout | `ENGINEERING_DEFAULT` | `sessions.py`, `lib/session.ts`, ADR-018/021, `api-types.test.ts` | Non-blocking; each documented at site of choice |
| A4 | All prospect/product data is synthetic (`SYNTHETIC-`, example domains) | `SYNTHETIC_PLACEHOLDER` | Fixture files, importer validator, tests | Must be replaced only after Q-019/G-03 |
| A5 | Fake model provider & fake email adapter stand in for real ones | `SYNTHETIC_PLACEHOLDER` | `model_gateway/providers`, `adapters/fake.py` | Real ones blocked at G-03 / G-07 (Q-012, Q-004) |
| A6 | Approver roster / who may approve | `UNRESOLVED_STAKEHOLDER_DECISION` (Q-005) | RBAC grants exist; roster does not | Blocking at G-10 rehearsal (T-071 notes a synthetic operator suffices) and hard-blocking at G-08 |
| A7 | OIDC provider & user roster | `UNRESOLVED_STAKEHOLDER_DECISION` (Q-026) | T-061b `BLOCKED`; stub confined to `local` | Blocking before any deployed environment |
| A8 | Email provider/mailbox/sender identity | `UNRESOLVED_STAKEHOLDER_DECISION` (Q-004, Q-015) | No adapter, no config | Blocking at G-07 |
| A9 | HubSpot adoption | `UNRESOLVED_STAKEHOLDER_DECISION` (Q-001, Q-010) | ADR-004 posture: "not checked", never "no relationship" | Blocking at G-05 only |
| A10 | npm advisories are unexploitable while the dashboard is local-only | `UNVERIFIED_EXTERNAL_ASSUMPTION` | T-152 reasoning; audit re-count: 3 high today | Becomes blocking the moment any deployment exists |

## 11. Findings (ordered by severity)

### STOP — none.

### HIGH

**H1 — Approval version pins are never set by the production path (T-157, already filed).**
`approve_message` calls `request_approval` without `product_status_version_id` or
`approved_claim_set_id` (audit-verified at `app/outreach_and_replies/approve_message.py:198`).
Consequence: §11.4's mandated `product_status_version` / `approved_claim_set_version` fields are
null on every send command the real path creates, and `invalidation_detail` **skips both currency
checks when pins are null** — so a superseded claim or product status does *not* invalidate such an
approval, at review or at dispatch. §8.4 says it must. No external harm is possible today (shadow
mode, fake adapter), but this is a substantive weakening of the claim-currency invariant in the
implemented truth, and the loop's own T-068a tests only reach these triggers by hand-building
approvals the production path cannot produce. **Action: T-157 must be `DONE` before G-10 is
evaluated; annotated on the gate.** (Credit: the loop found and filed this itself; the audit
confirms severity and gate linkage.)

### MEDIUM

**M1 — The entire implementation is uncommitted.** 118 paths of working-tree-only work on `main`,
public remote, no local history. A crash, bad script, or accidental `checkout --` loses months of
work with no recovery. Process §9 forbids the loop committing without explicit authorization — so
this needs a **user decision**, filed as T-158 (`BLOCKED` on that authorization). Consequence of
inaction: unbounded loss exposure; also, future audits have no stable baseline commit.

**M2 — T-137 substantially overlaps delivered work.** Its objective (revoke entry point, actor +
reason, audit event, non-dispatchability, terminal refusal) is now largely satisfied by
`approval.revoke()` (T-021) plus T-068a's endpoint and tests. Residual gaps found by audit: the
*function* accepts a blank reason (only the HTTP schema refuses it), and terminal-state refusal
surfaces as `IllegalTransition` rather than a domain error at the entry point. Left `READY` with
its block annotated to the residual scope, so the next implementer does two small things instead of
re-building what exists.

**M3 — T-152's advisory counts are stale.** Audit measured `{high: 3, critical: 0}` against the
recorded 7. The task's reasoning (local-only exposure) still holds; its text now overstates the
problem. Annotated.

### LOW

**L1 — Header prose says "No dashboard code exists yet"** while the dashboard has 4 routes, 5 live
actions, and 127 tests. Corrected in this pass (permitted ledger update).
**L2 — §5 intro says "Every gate below is LOCKED"** contradicting the G-01/G-02 `OPEN` rows two
lines later. Corrected to "unless marked OPEN in the table".
**L3 — T-068b was `PLANNED` with both dependencies `DONE`**, while the header simultaneously
claimed it `READY`. Status corrected to `READY` (this is the promotion the T-068a cycle forgot).
**L4 — `approvals_needing_attention` is an O(n) Python scan with per-approval queries.** Fine at
pilot volume; the ceiling is documented here so it is a known trade, not a surprise. No task filed
— revisit only if the attention list ever exceeds pilot scale.

## 12. Areas needing human/specialist double-checking

1. **T-009 / R-002:** only a stakeholder can supply the acceptance record.
2. **Commit authorization (M1/T-158):** only the user can grant it (process §9).
3. **Q-005 roster intent** before T-071's rehearsal is scheduled.
4. **Legal/compliance review of `compliance_elements` boilerplate** before any live gate — the
   template's adequacy is a legal judgment, not an engineering one.

## 13. Required before the loop resumes normal feature work

None blocking — the loop may resume. Recommended order: **T-157 first** (it is P1, small, and
closes H1), then T-068b.

## 14. Required before Stage 2 (G-10) can close

1. T-157 (H1) — version pins.
2. T-068b — attention surfacing on the card.
3. T-070 — real CSRF, replacing the bearer-only stance (A2).
4. T-071 — the non-engineer walkthrough with recorded evidence.
5. M2's residual T-137 delta (or its explicit fold-in/closure).
6. A decision on M1 — an uncommitted tree is a poor artifact to close a stage on.

## 15. Recommended next task

**T-157** — restore the §8.4/§11.4 pin semantics. It is the only open finding that weakens a
safety invariant, it is bounded (resolve two versions at approval time, pass them through, test
end to end), and its verification suites already exist.
