"use client";

import { useSyncExternalStore } from "react";

import { getSessionToken, serverSessionToken, subscribeToSessionToken } from "./session";

/**
 * The current session token, re-read whenever it changes (T-151b).
 *
 * A hook rather than component state so that signing in updates every component that cares
 * without the token being threaded through props — and so no component keeps a stale copy after
 * a `401` clears it.
 */
export function useSessionToken(): string | null {
  return useSyncExternalStore(subscribeToSessionToken, getSessionToken, serverSessionToken);
}
