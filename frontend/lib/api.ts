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
 * **The base URL is local, and refused if it is not.** Stage 2 is local development; the
 * dashboard has no deployed backend to talk to and §2 item 14 forbids reaching one merely
 * because the code path exists. `assertLocal` fails closed at module load rather than at the
 * first request, so a misconfigured environment is a startup error rather than a page that half
 * works. The day there is a real environment to point at, `T-061` and the deployment task relax
 * this deliberately — which is the point of it being one named function.
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
  const response = await fetch(new URL("/healthz", apiBaseUrl), {
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
  const response = await fetch(new URL(`/api/review/candidates/${candidateId}`, apiBaseUrl), {
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
  const response = await fetch(new URL("/api/auth/stub-sign-in", apiBaseUrl), {
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
  const response = await fetch(new URL("/api/auth/session", apiBaseUrl), {
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
  const response = await fetch(new URL("/api/auth/session", apiBaseUrl), {
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
    new URL(`/api/review/revisions/${revisionId}/edit`, apiBaseUrl),
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
    new URL(`/api/review/candidates/${candidateId}/approve`, apiBaseUrl),
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
  const response = await fetch(new URL(path, apiBaseUrl), {
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
