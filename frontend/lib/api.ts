import type { paths } from "./api-types";

/**
 * The dashboard's only way to reach the backend (T-060b; §18.1, §12.3, §23).
 *
 * **Types are generated, never written here.** `api-types.ts` comes from `openapi.json`, which
 * comes from the FastAPI application itself. Two tests hold that chain: a backend test asserts
 * the committed document still matches the application, and `tests/api-types.test.ts` asserts the
 * committed types still match the document. A hand-written interface here would look identical
 * and drift silently, which is the failure §23's typed-contract requirement exists to prevent.
 *
 * **Every request is a relative path, so the dashboard only ever talks to its own origin**
 * (`T-195`). It used to build absolute `http://localhost:8000` URLs, which made every call
 * cross-origin from the page's `localhost:3000`. The API registers no CORS middleware, so the
 * browser refused all of them and a reviewer could not get past sign-in. Nothing caught it
 * because the component tests stub `fetch`, and the `T-071a` exit-evidence run measured pages
 * *rendering* — which happens on the server, where this same code runs with no browser to object.
 *
 * **The fix is one origin, not permission to cross one.** `next.config.ts` rewrites `/api/*` and
 * the health routes to the backend, so what the browser issues is same-origin and the proxying is
 * the dev server's business. Adding `Access-Control-Allow-Origin` to the API would also have
 * worked and is worse: it puts a permissive header path into a service whose entire posture is
 * that external effects are structurally closed, and `SameSite` session cookies (`T-070a`) are
 * not sent cross-site regardless — so that route argues toward weakening the control that exists
 * to stop CSRF.
 *
 * **`apiBaseUrl` is therefore the proxy *target*, not a request prefix.** `next.config.ts` reads
 * it on the server; nothing in the browser does. `assertLocal` still fails closed at module load
 * — Stage 2 has no deployed backend to talk to, and §2 item 14 forbids reaching one merely
 * because the code path exists — so a misconfigured environment is still a startup error rather
 * than a page that half works. The day there is a real environment to point at, `T-061` and the
 * deployment task relax this deliberately, which is the point of it being one named function.
 */

const DEFAULT_BASE_URL = "http://localhost:8000";

/** Hostnames that are this machine. Nothing else is permitted in Stage 2. */
const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "[::1]", "::1"]);

export class NonLocalApiBaseUrl extends Error {}

export function assertLocal(rawUrl: string): URL {
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new NonLocalApiBaseUrl(`API base URL is not a URL: ${rawUrl}`);
  }
  if (!LOCAL_HOSTS.has(parsed.hostname)) {
    throw new NonLocalApiBaseUrl(
      `API base URL ${parsed.hostname} is not local. Stage 2 runs against a local backend only; ` +
        `pointing the dashboard elsewhere is a deployment decision, not a configuration edit.`,
    );
  }
  return parsed;
}

export const apiBaseUrl = assertLocal(process.env["NEXT_PUBLIC_API_BASE_URL"] ?? DEFAULT_BASE_URL);

type Liveness =
  paths["/healthz"]["get"]["responses"][200]["content"]["application/json"];

/**
 * Liveness, as an example of the generated types in use.
 *
 * `/healthz` and `/readyz` are the only endpoints the backend exposes today. The review-queue
 * endpoints the dashboard actually needs do not exist yet; each is its own task, and inventing a
 * client for one would be inventing the contract it is supposed to be generated from.
 */
export async function getLiveness(signal?: AbortSignal): Promise<Liveness> {
  const response = await fetch("/healthz", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`GET /healthz responded ${String(response.status)}`);
  }
  return (await response.json()) as Liveness;
}

/** §12.3's review card, as the backend describes it (`T-149`). */
export type CandidateDetail =
  paths["/api/review/candidates/{candidate_id}"]["get"]["responses"][200]["content"]["application/json"];

export type EvidenceRow = CandidateDetail["evidence"][number];
export type ClaimRow = CandidateDetail["approved_claims"][number];

/**
 * Everything the review card shows for one candidate.
 *
 * The type is the backend's, generated from its OpenAPI document — so a field the API renames
 * breaks the build here rather than rendering blank in front of a reviewer (§23).
 */
export async function getCandidateDetail(
  candidateId: string,
  token: string,
  signal?: AbortSignal,
): Promise<CandidateDetail> {
  const response = await fetch(`/api/review/candidates/${candidateId}`, {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, `GET /api/review/candidates/${candidateId}`);
  }
  return (await response.json()) as CandidateDetail;
}

/** An edit, as `T-065a`'s endpoint accepts it. */
export type EditRequest =
  paths["/api/review/revisions/{revision_id}/edit"]["post"]["requestBody"]["content"]["application/json"];

/** What the edit did: the new revision, the one it superseded, and any approval it retired. */
export type EditResponse =
  paths["/api/review/revisions/{revision_id}/edit"]["post"]["responses"][200]["content"]["application/json"];

/**
 * The endpoint refused, and said why in terms a reviewer can act on.
 *
 * The backend writes its own refusals as sentences — "this revision changed since it was loaded;
 * reload the card before editing", "the development sign-in stub is refused in production" — and
 * they are the message the reviewer needs. A generic "request failed" throws that away and leaves
 * them with nothing to do next.
 */
export class ApiRefused extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(detail);
  }
}

/** Kept under its `T-065a` name so the editing form's error handling reads unchanged. */
export { ApiRefused as EditRejected };

/** Turn a failed response into an `ApiRefused` carrying the backend's own `detail`. */
async function refusal(response: Response, what: string): Promise<ApiRefused> {
  let detail = `${what} responded ${String(response.status)}`;
  try {
    const body: unknown = await response.json();
    const reported = (body as { detail?: unknown }).detail;
    if (typeof reported === "string") {
      detail = reported;
    }
  } catch {
    // A non-JSON error body is not itself an error worth reporting over the status code.
  }
  return new ApiRefused(response.status, detail);
}

/** A session, as `T-151a`'s endpoints describe it. */
export type SessionInfo =
  paths["/api/auth/session"]["get"]["responses"][200]["content"]["application/json"];

/**
 * Sign in against the local development stub (`T-151a`).
 *
 * There is no password parameter and that is §12.2, not an omission: the real flow is managed
 * OIDC (`T-061b`, blocked on `Q-026`), and this stub exists so a developer can open the dashboard
 * before that provider is chosen. The endpoint refuses itself outside `local`, so this call is
 * safe to ship — pointing the dashboard at a deployed backend would get a `503` and a sentence
 * saying why, rather than a session.
 */
export async function signIn(email: string, signal?: AbortSignal): Promise<SessionInfo> {
  const response = await fetch("/api/auth/stub-sign-in", {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", "content-type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!response.ok) {
    throw await refusal(response, "POST /api/auth/stub-sign-in");
  }
  return (await response.json()) as SessionInfo;
}

/** The session ``token`` names, or `null` if the backend no longer honours it. */
export async function getSession(token: string, signal?: AbortSignal): Promise<SessionInfo | null> {
  const response = await fetch("/api/auth/session", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (response.status === 401) {
    // Expired, revoked, or never valid — `resolve` deliberately cannot tell them apart, so
    // neither can this. All three mean the same thing here: sign in again.
    return null;
  }
  if (!response.ok) {
    throw await refusal(response, "GET /api/auth/session");
  }
  return (await response.json()) as SessionInfo;
}

/** End the session ``token`` names. Signing out of a session the backend already dropped is not
 * an error — `T-151a` answers `204` — so this resolves either way. */
export async function signOut(token: string, signal?: AbortSignal): Promise<void> {
  const response = await fetch("/api/auth/session", {
    method: "DELETE",
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, "DELETE /api/auth/session");
  }
}

/**
 * Edit a revision, creating the next one (§10.5).
 *
 * **The token is a required argument, not read from ambient state.** `T-065a` refuses cookie
 * authentication on mutations, so this has to send `Authorization` deliberately; making the
 * caller pass it means a call site that has no session cannot compile its way into an
 * unauthenticated POST.
 *
 * A refusal — 401, 403, 404, 409, 422 — is an `EditRejected` carrying the backend's own `detail`,
 * because "this revision changed since it was loaded" and "reload the card" is the sentence a
 * reviewer needs. A generic "request failed" would throw that away.
 */
export async function editRevision(
  revisionId: string,
  request: EditRequest,
  token: string,
  signal?: AbortSignal,
): Promise<EditResponse> {
  const response = await fetch(
    `/api/review/revisions/${revisionId}/edit`,
    {
      method: "POST",
      ...(signal ? { signal } : {}),
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw await refusal(response, `POST /api/review/revisions/${revisionId}/edit`);
  }
  return (await response.json()) as EditResponse;
}

/** One address a candidate could be approved for (`T-154a`). */
export type ContactPointRow = CandidateDetail["contact_points"][number];

/** What an approval asks for, and what it answers with. */
export type ApproveRequest =
  paths["/api/review/candidates/{candidate_id}/approve"]["post"]["requestBody"]["content"]["application/json"];

export type ApproveResponse =
  paths["/api/review/candidates/{candidate_id}/approve"]["post"]["responses"][200]["content"]["application/json"];

/**
 * Approve a candidate for outreach to an exact recipient (ADR-008).
 *
 * The recipient is a required argument for the same reason it is on the server: ADR-008 approves
 * an *exact* address, so a call that could omit it would be a call that let the system choose.
 */
export async function approveCandidate(
  candidateId: string,
  request: ApproveRequest,
  token: string,
  signal?: AbortSignal,
): Promise<ApproveResponse> {
  const response = await fetch(
    `/api/review/candidates/${candidateId}/approve`,
    {
      method: "POST",
      ...(signal ? { signal } : {}),
      headers: {
        accept: "application/json",
        "content-type": "application/json",
        authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(request),
    },
  );
  if (!response.ok) {
    throw await refusal(response, `POST /api/review/candidates/${candidateId}/approve`);
  }
  return (await response.json()) as ApproveResponse;
}

/** Approving the exact words, as `T-067a`'s endpoint accepts it. */
export type ApproveMessageRequest =
  paths["/api/review/revisions/{revision_id}/approve"]["post"]["requestBody"]["content"]["application/json"];

export type ApproveMessageResponse =
  paths["/api/review/revisions/{revision_id}/approve"]["post"]["responses"][200]["content"]["application/json"];

/**
 * Approve an exact message revision for an exact recipient (§11.3, ADR-008).
 *
 * **This is the second approval, and it is not the same act as approving the candidate.** One
 * says this company is worth writing to; this one says *these words* may go to *this address*.
 * The architecture splits them deliberately, and until `T-205` the dashboard offered only the
 * first — the endpoint existed, `openapi.json` published it, and nothing called it. Three
 * independent rehearsal readers reached the drafted message, decided on it, and found no control
 * to record that decision (`T-071c`). The queue listed the revision as "awaiting approval" the
 * whole time.
 *
 * **The recipient is named rather than derived**, for ADR-008's reason: an address the form chose
 * is an address nobody approved. **`record_version` is sent** so the backend can refuse a revision
 * that changed after it was read — approving text you were not shown is exactly what the pin is
 * for, and a client that omitted it would be choosing to race.
 */
export async function approveRevision(
  revisionId: string,
  request: ApproveMessageRequest,
  token: string,
  signal?: AbortSignal,
): Promise<ApproveMessageResponse> {
  const response = await fetch(`/api/review/revisions/${revisionId}/approve`, {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await refusal(response, `POST /api/review/revisions/${revisionId}/approve`);
  }
  return (await response.json()) as ApproveMessageResponse;
}

/** The candidate review queue (`T-063a`) and the revision review queue (`T-063b`). */
export type CandidatePage =
  paths["/api/review/candidates"]["get"]["responses"][200]["content"]["application/json"];

export type CandidateQueueRow = CandidatePage["rows"][number];

export type RevisionPage =
  paths["/api/review/revisions"]["get"]["responses"][200]["content"]["application/json"];

export type RevisionQueueRow = RevisionPage["rows"][number];

/**
 * Candidates waiting on a person, oldest first.
 *
 * No `state` parameter, and that is the endpoint's decision rather than an omission: without one
 * it filters to `review_pending`, because "the queue" means what is *waiting*. Passing the state
 * explicitly here would duplicate that decision in a second place, and the copy that drifts is
 * the one further from the query.
 */
export async function listCandidateQueue(
  token: string,
  signal?: AbortSignal,
): Promise<CandidatePage> {
  const response = await fetch("/api/review/candidates", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, "GET /api/review/candidates");
  }
  return (await response.json()) as CandidatePage;
}

/** Revisions waiting on a person, longest-waiting first, each with its backlog age (§17.5). */
export async function listRevisionQueue(
  token: string,
  signal?: AbortSignal,
): Promise<RevisionPage> {
  const response = await fetch("/api/review/revisions", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, "GET /api/review/revisions");
  }
  return (await response.json()) as RevisionPage;
}

/** §17.5's operational dashboard, as `T-069a` serves it. */
export type OperationsOverview =
  paths["/api/operations/overview"]["get"]["responses"][200]["content"]["application/json"];

export type DeadJobRow = OperationsOverview["dead_job_sample"][number];

/** The switches `T-069b` exposes. Taken from the generated path so it cannot drift from the API. */
export type FlagKey =
  paths["/api/operations/flags/{key}"]["post"]["parameters"]["path"]["key"];

export type FlagChangeRequest =
  paths["/api/operations/flags/{key}"]["post"]["requestBody"]["content"]["application/json"];

export type FlagChangeResponse =
  paths["/api/operations/flags/{key}"]["post"]["responses"][200]["content"]["application/json"];

/** What the system is doing right now. Administrator only — a `403` here is not a sign-in problem. */
export async function getOperationsOverview(
  token: string,
  signal?: AbortSignal,
): Promise<OperationsOverview> {
  const response = await fetch("/api/operations/overview", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, "GET /api/operations/overview");
  }
  return (await response.json()) as OperationsOverview;
}

/**
 * Throw or release one §17.6 switch.
 *
 * The reason is part of the request type because the backend requires one in *both* directions:
 * releasing a pause is the more consequential half and is exactly what an incident review asks
 * about.
 */
export async function setOperationalFlag(
  key: FlagKey,
  request: FlagChangeRequest,
  token: string,
  signal?: AbortSignal,
): Promise<FlagChangeResponse> {
  const response = await fetch(`/api/operations/flags/${key}`, {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await refusal(response, `POST /api/operations/flags/${key}`);
  }
  return (await response.json()) as FlagChangeResponse;
}

/** §7.5's flag: approvals that no longer authorize a send (`T-068a`). */
export type AttentionPage =
  paths["/api/review/attention/approvals"]["get"]["responses"][200]["content"]["application/json"];

export type AttentionRow = AttentionPage["items"][number];

/**
 * Every approval that has gone stale, oldest first.
 *
 * No campaign filter is passed. The endpoint accepts one, and nothing in the dashboard has a
 * campaign to filter by yet — a parameter here would be a parameter with no caller, and the list
 * a reviewer needs is "what needs attention", not "what needs attention in one campaign".
 */
export async function listStaleApprovals(
  token: string,
  signal?: AbortSignal,
): Promise<AttentionRow[]> {
  const response = await fetch("/api/review/attention/approvals", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, "GET /api/review/attention/approvals");
  }
  return ((await response.json()) as AttentionPage).items;
}

export type RefuseMessageRequest =
  paths["/api/review/revisions/{revision_id}/refuse"]["post"]["requestBody"]["content"]["application/json"];

export type RefuseMessageResponse =
  paths["/api/review/revisions/{revision_id}/refuse"]["post"]["responses"][200]["content"]["application/json"];

/**
 * Record that these exact words must not be sent (`T-208`; §8.2's `review_pending -> invalidated`).
 *
 * The third thing a reviewer can do with a draft, beside approving it and editing it. It carries
 * no subject and no body on purpose: a refusal that required replacement copy is the gap this
 * closes, and three rehearsal readers hit it in a row.
 */
export async function refuseRevision(
  revisionId: string,
  request: RefuseMessageRequest,
  token: string,
  signal?: AbortSignal,
): Promise<RefuseMessageResponse> {
  const response = await fetch(`/api/review/revisions/${revisionId}/refuse`, {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await refusal(response, `POST /api/review/revisions/${revisionId}/refuse`);
  }
  return (await response.json()) as RefuseMessageResponse;
}

/** §7.5's other half: drafts whose latest revision failed validation (`T-209`). */
export type StrandedRevisionPage =
  paths["/api/review/attention/revisions"]["get"]["responses"][200]["content"]["application/json"];

export type StrandedRevisionRow = StrandedRevisionPage["items"][number];

/**
 * Every candidate whose latest draft cannot be approved by anyone, longest-waiting first.
 *
 * The same shape as `listStaleApprovals` and the same reason for having no campaign filter: the
 * question a reviewer opens this page with is "what is stuck", not "what is stuck in one
 * campaign".
 */
export async function listStrandedRevisions(
  token: string,
  signal?: AbortSignal,
): Promise<StrandedRevisionRow[]> {
  const response = await fetch("/api/review/attention/revisions", {
    ...(signal ? { signal } : {}),
    headers: { accept: "application/json", authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw await refusal(response, "GET /api/review/attention/revisions");
  }
  return ((await response.json()) as StrandedRevisionPage).items;
}

export type RevokeApprovalRequest =
  paths["/api/review/approvals/{approval_id}/revoke"]["post"]["requestBody"]["content"]["application/json"];

export type RevokeApprovalResponse =
  paths["/api/review/approvals/{approval_id}/revoke"]["post"]["responses"][200]["content"]["application/json"];

/**
 * Withdraw an approval so it can never dispatch (§8.2's `approved -> revoked`, §17.6).
 *
 * The reason is part of the request type rather than optional here, because the backend requires
 * one: §17.6 wants operational actions explicable, and a revocation nobody can explain later is
 * indistinguishable from a fault.
 */
export async function revokeApproval(
  approvalId: string,
  request: RevokeApprovalRequest,
  token: string,
  signal?: AbortSignal,
): Promise<RevokeApprovalResponse> {
  const response = await fetch(`/api/review/approvals/${approvalId}/revoke`, {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await refusal(response, `POST /api/review/approvals/${approvalId}/revoke`);
  }
  return (await response.json()) as RevokeApprovalResponse;
}

/** §10.6's eleven categories, as the backend defines them (`T-066a`). */
export type DecisionCategory =
  paths["/api/review/candidates/{candidate_id}/reject"]["post"]["requestBody"]["content"]["application/json"]["category"];

export type RejectRequest =
  paths["/api/review/candidates/{candidate_id}/reject"]["post"]["requestBody"]["content"]["application/json"];

export type DeferRequest =
  paths["/api/review/candidates/{candidate_id}/defer"]["post"]["requestBody"]["content"]["application/json"];

export type DecisionResponse =
  paths["/api/review/candidates/{candidate_id}/reject"]["post"]["responses"][200]["content"]["application/json"];

async function decide<Body>(
  candidateId: string,
  action: "reject" | "defer" | "request-research",
  request: Body,
  token: string,
  signal?: AbortSignal,
): Promise<DecisionResponse> {
  const path = `/api/review/candidates/${candidateId}/${action}`;
  const response = await fetch(path, {
    method: "POST",
    ...(signal ? { signal } : {}),
    headers: {
      accept: "application/json",
      "content-type": "application/json",
      authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await refusal(response, `POST ${path}`);
  }
  return (await response.json()) as DecisionResponse;
}

/** End this candidate, with the §10.6 category the reviewer chose. */
export async function rejectCandidate(
  candidateId: string,
  request: RejectRequest,
  token: string,
  signal?: AbortSignal,
): Promise<DecisionResponse> {
  return decide(candidateId, "reject", request, token, signal);
}

/** Pause this candidate until a date or an event. */
export async function deferCandidate(
  candidateId: string,
  request: DeferRequest,
  token: string,
  signal?: AbortSignal,
): Promise<DecisionResponse> {
  return decide(candidateId, "defer", request, token, signal);
}

export type RequestResearchRequest =
  paths["/api/review/candidates/{candidate_id}/request-research"]["post"]["requestBody"]["content"]["application/json"];

/**
 * Ask for more evidence about a candidate that stays in review (ADR-022).
 *
 * Not a state change, which is why it returns the same `DecisionResponse` as reject and defer but
 * with the candidate still `review_pending` — the dashboard shows that rather than assuming it.
 */
export async function requestMoreResearch(
  candidateId: string,
  request: RequestResearchRequest,
  token: string,
  signal?: AbortSignal,
): Promise<DecisionResponse> {
  return decide(candidateId, "request-research", request, token, signal);
}
