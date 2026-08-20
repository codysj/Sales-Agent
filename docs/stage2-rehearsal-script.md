# Stage 2 rehearsal — running sheet

For the **G-10** gate: *a non-engineer completes reviews without understanding the agent stack.*

**There are two rehearsals, and they buy different things** ([ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md)):

| | Task | Who sits down | What it unlocks |
|---|---|---|---|
| **Human rehearsal** — Parts A, B, C | `T-071b` | one non-engineer, observed | **G-10 in full**, and it stays a precondition of **G-07** and **G-08** |
| **Agent rehearsal** — Parts A, B, D | `T-071c` | ≥3 LLM agents, independently | **G-10 for Stage 3 only** |

Parts **A** (setup) and **B** (the page the reviewer is handed) are **shared** — the same
environment and the same brief, so the two results are comparable. Part **C** is the human
observation sheet; Part **D** is the agent protocol and its record.

> **Neither path substitutes for the other, and the agent result is never written up as satisfying
> the gate's own words.** "A non-engineer" means a person. ADR-030 records what the agent evidence
> does and does not establish, and why the line falls where it does.

Both are transcribed into [stage2-exit-evidence.md](stage2-exit-evidence.md) §5, into their own
labelled subsections.

> [!IMPORTANT]
> **Confirm the review queue actually renders rows in a browser before scheduling anybody.** This
> block used to say neither rehearsal could run at all: the dashboard's API calls were
> cross-origin, the browser blocked them, and a reviewer — human or agent — could not get past
> sign-in. `T-195` fixed that on 2026-08-11 and rehearsals have run since, but the warning stayed
> here telling an operator not to schedule anybody. An instruction that has outlived its reason is
> worse than no instruction, because somebody acts on it. The check it asked for is worth keeping
> on its own merits, so that is what remains.

---

## Part A — operator runbook (before they arrive)

Setup is deliberately **out of scope** for the reviewer. The gate asks whether they can complete a
review, not whether they can install PostgreSQL. Record in §5 that §0–§1 were operator-run.

From the repository root:

```bash
docker compose up -d db
```

From `backend/`, in order:

```bash
uv run alembic upgrade head
uv run python -m app.cli seed_synthetic
uv run python -m app.cli start_campaign synthetic-sodium-battery
uv run python -m app.cli import_prospects
uv run python -m app.cli run_worker
uv run python -m app.cli grant_local_reviewer
```

Then two servers, one per terminal — the API from `backend/`, the dashboard from `frontend/`:

```bash
uv run uvicorn app.main:app --port 8000
```

```bash
npm run dev
```

Open <http://localhost:3000>, confirm the review queue has rows, then sign out and hand over.

### The three rules

1. **Do not coach.** Not a hint, not a pointed silence at the right moment. If they ask you
   something, write the question down verbatim and say *"I want to see what you'd do."* The
   questions are the finding — more than the outcome is.
2. **Do not point out that two of the three cards carry no evidence.** Whether they notice, and
   what they do about it, is one of the things you are measuring.
3. **Run the worker again after they approve a candidate.** Approving queues the drafting job; it
   does not run it. Until you re-run it, no message exists for them to review, and message review
   is half the gate:

   ```bash
   uv run python -m app.cli run_worker
   ```

   Do this quietly. Tell them the page may need a refresh; do not explain why.

### If something breaks

Stop the clock, note exactly what they were doing, and finish the session if you can. A broken step
is a finding, not a failed rehearsal — file it as a task and record it in §5.

---

## Part B — the reviewer's page (hand them only this)

> ### Reviewing outreach at Matrix Power
>
> We are about to start contacting companies about our energy-storage products. Before anything
> goes out, a person has to look at each one and decide.
>
> **That person is you, for the next half hour.**
>
> **None of these are real companies.** Every name, address and fact on the screen is invented for
> practice. **Nothing you do will send anything to anyone** — the system is switched off at the
> sending end, and stays that way.
>
> #### Signing in
>
> Go to **http://localhost:3000** and sign in as:
>
> `_______________________________________`  *(operator: write the reviewer address here)*
>
> There is no password.
>
> #### What we would like you to do
>
> 1. Look at the companies waiting for a decision. For **each one**, decide whether we should
>    contact them — and record your decision using whatever the screen offers.
> 2. For at least one, decide **yes**.
> 3. After that, a draft message will appear for the one you said yes to. Read it and decide
>    whether those words should go to that company.
>
> That is the whole task. How you do it is up to you.
>
> #### Two things that matter more than finishing
>
> - **If you get stuck, say so and stop.** Getting stuck is a useful result. Pretending to
>   understand is not.
> - **Say what you are thinking as you go**, especially when something is unclear, surprising, or
>   makes you hesitate.
>
> You cannot break anything, and there is no wrong decision — we are testing the screen, not you.

---

## Part C — observation sheet, human rehearsal (`T-071b`)

**Reviewer:** ____________________  **Role:** ____________________  **Date:** ____________

**Start:** ______  **First decision recorded:** ______  **Message decision:** ______  **End:** ______

### Completed unaided?

| Step | Unaided | Asked / stuck | Note |
|---|---|---|---|
| Signed in | ☐ | ☐ | |
| Found the waiting work | ☐ | ☐ | |
| Opened a card and read it | ☐ | ☐ | |
| Recorded a decision on card 1 | ☐ | ☐ | |
| Recorded a decision on cards 2 and 3 | ☐ | ☐ | |
| Found the draft message afterwards | ☐ | ☐ | |
| Decided on the message | ☐ | ☐ | |

### Every question they asked, verbatim

Do not paraphrase. Do not filter the ones that seem silly.

1.
2.
3.

### Did they notice the missing evidence?

Two of the three cards record no supporting evidence at all, and the card says so. Did they see it?
Did it change their decision? **Unprompted / prompted / not at all:** ____________

### The closing question

Ask this only at the very end, and write the answer down as they say it:

> *"The one you approved — what happens to it next?"*

Answer: ________________________________________________

They do not need the internals. They should be able to say something like *a message will go to
that person once it is approved, and nothing has been sent yet.* If they cannot, the dashboard has
not told them what it needed to.

### Their confirmation

> *"Could you do this on your own tomorrow, without me in the room?"*

**Yes / With notes / No:** ____________  Their words: ____________________________

### Gate decision

**G-10 — a non-engineer completes reviews without understanding the agent stack.**

**Met / Not met:** ____________  **Decided by:** ____________  **Date:** ____________

If not met, the specific reason, and the task ID filed for it: ____________________

---

## Part D — agent rehearsal (`T-071c`)

An LLM agent team stands in for the reviewer. It measures the same thing Part C does — **is this
interface usable by someone who does not know how it works** — across more independent readings
than one session gives. It does **not** measure whether a person can bear the approval
responsibility, which is why it unlocks Stage 3 only. Read
[ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md) before running this; the
limitations are the point of the record.

### D.1 — The six conditions

A run that violates any of these is discarded, not corrected. They exist because a rehearsal that
fails them produces a document indistinguishable from a real one.

1. **No repository access.** The agent may not read this codebase, this file, the specification, the
   ledger, or any commit. Its inputs are Part B and the running browser, and nothing else. An agent
   that has seen the repository in the same context is disqualified for that run.
2. **Fresh context per run.** No agent sees another's transcript, findings, or conclusion. Not a
   summary, not a hint about where the last one struggled.
3. **At least three independent runs.** One run is an anecdote. The finding is what recurs.
4. **Verbatim transcripts.** Every question, hesitation, and wrong turn recorded as produced —
   including the ones that look trivial or embarrassing. Filtering is where this kind of evidence
   usually dies.
5. **No coaching, and no channel for it.** The operator does not answer mid-run. Do not add one
   "just in case"; the absence is what makes the result mean anything.
6. **A negative result is a result.** An agent that cannot complete the flow closes `T-071c` with
   the gate still locked and a defect filed — exactly as a human failure would. Do not re-run until
   it passes.

### D.2 — Operator setup

> [!IMPORTANT]
> **This run must use a throwaway database, created for it and dropped afterwards.** That is a
> condition of the permission that lets an agent approve at all
> ([ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md)), not a tidiness preference.
> The agent will approve a candidate, which writes an `Approval` row attributed to the reviewer
> account; a database that does not survive the rehearsal cannot leave agent-made approvals sitting
> in one an audit would later read. Point `DATABASE_URL` at a fresh database before Part A, and drop
> it when you have transcribed the results.
>
> The second condition is §D.4's: **§5.2 of the exit evidence must state that the approvals were
> agent-made.** A run missing either condition falls outside the permission and does not count.

Part A, unchanged, plus:

- Confirm the review queue renders rows **in a browser**, not just that the pages return `200`
  (`T-195`).
- Give the agent browser control and the Part B text. Nothing else — no repository path, no
  architecture summary, no explanation of what a "candidate" is.
- Fill in the sign-in address on the Part B page before handing it over, as you would for a person.
- Re-run the worker after an approval, quietly, exactly as rule 3 of Part A says. The agent is told
  the page may need a refresh and is not told why.

### D.3 — Per-run record

Copy this block once per agent run. **Run:** ____ of ____ **Model / harness:** ______________
**Date:** __________ **Wall-clock:** ______

| Step | Unaided | Stuck / asked | Note |
|---|---|---|---|
| Signed in | ☐ | ☐ | |
| Found the waiting work | ☐ | ☐ | |
| Opened a card and read it | ☐ | ☐ | |
| Recorded a decision on card 1 | ☐ | ☐ | |
| Recorded decisions on cards 2 and 3 | ☐ | ☐ | |
| Found the draft message afterwards | ☐ | ☐ | |
| Decided on the message | ☐ | ☐ | |

**Every question it asked, verbatim** (do not paraphrase, do not filter):

1.
2.
3.

**Did it notice that two of the three cards carry no evidence?**
**Unprompted / prompted / not at all:** __________ Did it change the decision? __________

**The closing question**, asked at the very end and answered from the screens alone:

> *"The one you approved — what happens to it next?"*

Answer: ________________________________________________

**Anything it did that a person plausibly would not** — read past an unclear label, infer a
convention, recover from a dead end without hesitating. This column is the honest one, and it is
what stops the run reading as stronger evidence than it is:

________________________________________________

### D.4 — Across the runs

Only what appears in **more than one** run is a finding. Single-run oddities go in the notes.

| Recurring problem | Runs affected | Task filed |
|---|---|---|
| | | |

**Did every run complete the flow?** **Yes / No:** ______

**Stage 3 unlock decision.** Per ADR-030 this opens **G-10 for Stage 3 only** — `T-080`, `T-081`,
`T-083`, `T-084`, `T-085`. It does not open Stage 4 or Stage 5 scope, and it is not a G-07 or G-08
precondition.

**Granted / Not granted:** __________ **Decided by:** __________ **Date:** __________

### D.5 — The two conditions of the permission

Both must be recorded, and both are conditions rather than preferences
([ADR-030](adr/ADR-030-the-g-10-rehearsal-has-two-evidence-paths.md)).

- **The database this run used has been dropped.** Name it, and confirm: ____________________
- **§5.2 states the approvals in this run were agent-made.** ☐

A run that kept its database, or evidence that does not say the approvals were agent-made, falls
outside the permission and does not count as a rehearsal.

**Still required for the full gate:** the Part C human rehearsal (`T-071b`), before any Stage 4
work begins.

---

## Afterwards

1. Transcribe into [stage2-exit-evidence.md](stage2-exit-evidence.md) §5 — Part C into §5.1, Part D
   into §5.2. Timings observed, not estimated.
2. File anything the rehearsal exposed as its own task; do not fold fixes into `T-071b` or
   `T-071c`.
3. Close the task that ran, and record the corresponding **G-10** decision in `tasks.md` §5:
   - `T-071c` → Stage 3 scope only, gate otherwise still **LOCKED**.
   - `T-071b` → the gate itself, decided on that evidence.
4. **If both have run, compare them.** Where the person and the agents diverged is the most useful
   thing this structure produces, and ADR-030 asks for it to be recorded either way.
