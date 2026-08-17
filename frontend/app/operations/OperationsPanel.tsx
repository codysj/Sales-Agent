"use client";

import { useState } from "react";

import { ApiRefused, setOperationalFlag } from "../../lib/api";
import type { FlagKey, OperationsOverview } from "../../lib/api";
import { getSessionToken } from "../../lib/session";

/**
 * The operations panel (T-069c; §17.5, §17.6, §12.3).
 *
 * **Shadow mode is the first thing on the page, and it is a sentence rather than a field.** An
 * operator opening this during an incident is asking one question before any other: is anything
 * leaving the building? A row in a table of fifteen numbers answers it only to somebody who
 * already knows to look. It is also the *effective* answer — configuration **or** the flag —
 * because reporting one of them would say outreach is live while a switch says otherwise.
 *
 * **Dead jobs are shown with their reasons.** §17.1 guarantees every dead job carries one, and a
 * count without it sends the operator to the database — which is the moment a dashboard stops
 * being used. The endpoint bounds the sample; the count beside it says how many there are in all.
 *
 * **Every switch needs a typed reason, and the button will not submit without one.** §17.6 wants
 * operational actions explicable, the backend refuses a blank reason in both directions, and a
 * button that let an administrator discover that by being refused would have wasted the decision
 * they had already made.
 *
 * **Nothing here is a start button.** Releasing a switch cannot enable an external effect that
 * configuration has not already enabled — `T-069b` proves that server-side — and the panel says
 * so rather than leaving an administrator to wonder what "off" turns on.
 *
 * It renders from a prop and fetches nothing; `lib/api.ts` is the only module that reaches the
 * backend (`tests/no-network.test.ts`). The one call made here goes through it.
 */

/** The three system-wide switches, with what each one stops. Scoped keys are not shown: they
 *  address one product or claim version and the endpoint refuses them. */
const SWITCHES: ReadonlyArray<readonly [FlagKey, string, string]> = [
  ["global_pause", "Global pause", "Stops all new consequential work. Queued work stays queued."],
  ["shadow_mode", "Shadow mode", "External-effect adapters refuse to act at all."],
  ["outbound_email_disabled", "Outbound email disabled", "Narrower than shadow mode: email only."],
];

function formatAge(seconds: number | null): string {
  // `null` and `0` are different answers — nothing waiting, and something that arrived this
  // instant — and an operator reads them differently.
  if (seconds === null) {
    return "nothing waiting";
  }
  if (seconds < 60) {
    return `${String(seconds)}s`;
  }
  if (seconds < 3600) {
    return `${String(Math.floor(seconds / 60))}m`;
  }
  return `${String(Math.floor(seconds / 3600))}h`;
}

type Outcome =
  | { kind: "idle" }
  | { kind: "sending" }
  | { kind: "refused"; detail: string };

function Switch({
  flagKey,
  label,
  effect,
  isOn,
  onChanged,
}: {
  flagKey: FlagKey;
  label: string;
  effect: string;
  isOn: boolean;
  onChanged: (key: FlagKey, enabled: boolean, shadowMode: boolean) => void;
}) {
  const [reason, setReason] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ kind: "idle" });

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (reason.trim() === "") {
      return;
    }
    const token = getSessionToken();
    if (token === null) {
      setOutcome({
        kind: "refused",
        detail: "You are not signed in, so nothing was changed. Sign in and try again.",
      });
      return;
    }

    setOutcome({ kind: "sending" });
    try {
      const response = await setOperationalFlag(flagKey, { enabled: !isOn, reason }, token);
      setReason("");
      setOutcome({ kind: "idle" });
      onChanged(flagKey, response.enabled, response.shadow_mode);
    } catch (error) {
      setOutcome({
        kind: "refused",
        detail:
          error instanceof ApiRefused
            ? error.detail
            : `The switch could not be changed: ${String(error)}`,
      });
    }
  }

  const action = isOn ? "Turn off" : "Turn on";

  return (
    <li>
      <h3>{label}</h3>
      <p>
        Currently <strong>{isOn ? "on" : "off"}</strong>. {effect}
      </p>
      <form
        onSubmit={(event) => {
          void submit(event);
        }}
        aria-label={`${action} ${label}`}
      >
        <label htmlFor={`reason-${flagKey}`}>Why are you doing this?</label>
        <input
          type="text"
          id={`reason-${flagKey}`}
          value={reason}
          onChange={(event) => {
            setReason(event.target.value);
          }}
        />
        <button
          type="submit"
          disabled={reason.trim() === "" || outcome.kind === "sending"}
          title={reason.trim() === "" ? "An operational change needs a reason (§17.6)" : undefined}
        >
          {outcome.kind === "sending" ? "Working…" : action}
        </button>
      </form>
      {outcome.kind === "refused" && <p role="alert">{outcome.detail}</p>}
    </li>
  );
}

export function OperationsPanel({ overview }: { overview: OperationsOverview }) {
  const [state, setState] = useState(overview);

  const inForce = new Set(state.flags_in_force);

  function applyChange(key: FlagKey, enabled: boolean, shadowMode: boolean) {
    setState((current) => {
      const flags = new Set(current.flags_in_force);
      if (enabled) {
        flags.add(key);
      } else {
        flags.delete(key);
      }
      return { ...current, flags_in_force: [...flags].sort(), shadow_mode: shadowMode };
    });
  }

  return (
    <>
      {/* First on the page, deliberately. See the module docstring. */}
      <section aria-labelledby="posture">
        <h2 id="posture">Safety posture</h2>
        <p role="status">
          {state.shadow_mode
            ? "Shadow mode is ON. No external effect can happen: adapters refuse to act."
            : "Shadow mode is OFF. What can leave the building is decided by the switches below and by whether live sending has been authorized (gate G-07)."}
        </p>
      </section>

      <section aria-labelledby="switches">
        <h2 id="switches">Switches</h2>
        <p>
          Every change needs a reason, in both directions. Turning a switch <em>off</em> cannot
          enable anything configuration has not already enabled, and email still cannot be sent
          until that is authorized separately (gate G-07).
        </p>
        <ul aria-label="Operational switches">
          {SWITCHES.map(([key, label, effect]) => (
            <Switch
              key={key}
              flagKey={key}
              label={label}
              effect={effect}
              isOn={inForce.has(key)}
              onChanged={applyChange}
            />
          ))}
        </ul>
      </section>

      <section aria-labelledby="work">
        <h2 id="work">Work in flight</h2>
        <dl>
          <dt>Jobs by state</dt>
          <dd>
            {Object.keys(state.jobs_by_state).length === 0
              ? "No jobs recorded."
              : Object.entries(state.jobs_by_state)
                  .map(([name, count]) => `${name}: ${String(count)}`)
                  .join(" · ")}
          </dd>
          <dt>Oldest queued job</dt>
          <dd>{formatAge(state.oldest_queued_job_age_seconds)}</dd>
          <dt>Outbox backlog</dt>
          <dd>
            {state.outbox_pending} pending · oldest{" "}
            {formatAge(state.oldest_pending_outbox_age_seconds)}
          </dd>
          <dt>Delivery ambiguous</dt>
          <dd>{state.delivery_ambiguous_threads} thread(s) that may have arrived</dd>
          <dt>Review backlog</dt>
          <dd>
            {state.candidates_awaiting_review} candidate(s) · {state.revisions_awaiting_review}{" "}
            message(s) · oldest {formatAge(state.oldest_review_item_age_seconds)}
          </dd>
          <dt>Claim invalidations</dt>
          <dd>{state.claim_invalidations} approval(s) whose claim set was superseded</dd>
          <dt>Suppressed sends</dt>
          {/* Attempts, not people: the same address refused twice is two. A campaign whose every
              send is being refused used to look identical to one with nothing to send (T-161). */}
          <dd>{state.suppressed_send_attempts} send(s) refused because the recipient is suppressed</dd>
        </dl>
      </section>

      <section aria-labelledby="dead">
        <h2 id="dead">Dead jobs</h2>
        {state.dead_job_sample.length === 0 ? (
          <p>No dead jobs. Nothing has exhausted its retries.</p>
        ) : (
          <>
            <p>
              {state.dead_jobs} in total; the most recent {state.dead_job_sample.length} are shown
              with the reason each one stopped.
            </p>
            <ul aria-label="Dead jobs">
              {state.dead_job_sample.map((job) => (
                <li key={job.job_id}>
                  <strong>{job.job_type}</strong> — {job.reason} (attempt {job.attempt_count}
                  {job.requires_human_review ? ", needs a human" : ""})
                </li>
              ))}
            </ul>
          </>
        )}
      </section>

      {state.not_measured.length > 0 && (
        <section aria-labelledby="not-measured">
          <h2 id="not-measured">Not measured</h2>
          {/* Stated rather than shown as a zero: "nothing is being suppressed" is a claim nobody
              checked, and an operator would act on it. */}
          <ul>
            {state.not_measured.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        </section>
      )}
    </>
  );
}
