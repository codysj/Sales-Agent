# Stage 2 rehearsal — running sheet

For `T-071b`, the **G-10** gate: *a non-engineer completes reviews without understanding the agent
stack.* Three parts. **A** is yours. **B** is the only thing the reviewer sees. **C** is what you
write down.

Results are transcribed into [stage2-exit-evidence.md](stage2-exit-evidence.md) §5 afterwards.

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

## Part C — observation sheet (you fill this in)

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

## Afterwards

1. Transcribe Parts C into [stage2-exit-evidence.md](stage2-exit-evidence.md) §5 — timings
   observed, not estimated.
2. File anything the rehearsal exposed as its own task; do not fold fixes into `T-071b`.
3. Set `T-071b` to `DONE` and record the **G-10** decision in `tasks.md` §5.
