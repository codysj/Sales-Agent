/**
 * Where the dashboard keeps its session token (T-065b; §12.2, §17.5).
 *
 * `T-065a` made mutations refuse cookie authentication — a CSRF attack rides on credentials the
 * browser attaches by itself, and a bearer token never is one — so an editing form has to hold a
 * token and send it deliberately. This module is the one place that decides where it lives.
 *
 * **`sessionStorage`, not `localStorage`.** A review session should not outlive the tab it was
 * opened in; §17.5 wants short sessions and `T-061a` gave them an eight-hour expiry, and a token
 * that survives closing the browser quietly undoes that.
 *
 * **Obtaining a token is `T-151a`'s endpoint; putting it here is `T-151b`'s screen.** This module
 * only reads and writes the one place it lives, so there is exactly one answer to "where is the
 * session" and no component has to know it.
 *
 * **It is an external store, so components read it with `useSyncExternalStore`.** That is what
 * the hook is for, and it is not ceremony: `sessionStorage` does not exist while rendering on the
 * server, so a component that read it during render would produce markup the client immediately
 * disagreed with, and one that read it in a mount effect would set state on every mount for a
 * value that had not changed. `getServerSnapshot` answers `null` — signed out — which is the only
 * honest answer the server can give about a store it cannot see.
 */

export const SESSION_TOKEN_KEY = "mp_session_token";

/** The current session token, or `null` when there is none — including on the server. */
export function getSessionToken(): string | null {
  // `sessionStorage` does not exist during server rendering, and the check is cheaper than the
  // try/catch that would otherwise be needed on every read.
  if (typeof window === "undefined") {
    return null;
  }
  return window.sessionStorage.getItem(SESSION_TOKEN_KEY) || null;
}

/** Remember ``token`` for this tab. */
export function setSessionToken(token: string): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.setItem(SESSION_TOKEN_KEY, token);
  announce();
}

/** Forget the token. Called after signing out, and after any `401` — a token the backend has
 * stopped honouring is worse than none, because every later request fails for a reason the
 * dashboard would keep attributing to something else. */
export function clearSessionToken(): void {
  if (typeof window === "undefined") {
    return;
  }
  window.sessionStorage.removeItem(SESSION_TOKEN_KEY);
  announce();
}

const listeners = new Set<() => void>();

function announce(): void {
  for (const listener of listeners) {
    listener();
  }
}

/**
 * Subscribe to changes. `storage` events cover another tab; `announce` covers this one, because
 * the browser does not fire `storage` for the tab that made the change.
 */
export function subscribeToSessionToken(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

/** `null` on the server, which is the only honest answer about a store it cannot see. */
export function serverSessionToken(): null {
  return null;
}
