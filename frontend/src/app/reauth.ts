/**
 * Signing in again without leaving the page (ADR-0013, M20).
 *
 * When a write (create, update, delete, a password form) comes back `401
 * not_authenticated`, e.g. after the idle timeout, the API client asks this
 * store instead of ending the session at once. <ReauthDialog> shows a sign-in
 * dialog; the write's promise stays pending, so the form keeps its input in
 * memory (never in browser storage) and the same request is sent again after
 * the same account signs in.
 */

import type { QueryClient } from "@tanstack/react-query";

import type { ReauthOutcome } from "@/api/client";
import { queryKeys } from "@/api/hooks";

export interface ReauthStore {
  /** Ask for a sign-in; concurrent callers share one dialog and outcome. */
  request: () => Promise<ReauthOutcome>;
  /** Resolve the pending request (called by the dialog). */
  settle: (outcome: ReauthOutcome) => void;
  isOpen: () => boolean;
  subscribe: (listener: () => void) => () => void;
}

export function createReauthStore(): ReauthStore {
  let pending: Promise<ReauthOutcome> | null = null;
  let resolve: ((outcome: ReauthOutcome) => void) | null = null;
  const listeners = new Set<() => void>();
  const notify = () => {
    for (const listener of listeners) listener();
  };
  return {
    request: () => {
      if (pending === null) {
        pending = new Promise<ReauthOutcome>((done) => {
          resolve = done;
        });
        notify();
      }
      return pending;
    },
    settle: (outcome) => {
      const done = resolve;
      pending = null;
      resolve = null;
      notify();
      done?.(outcome);
    },
    isOpen: () => pending !== null,
    subscribe: (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
  };
}

/**
 * The API client's `reauthenticate` option: only a signed-in admin is asked;
 * for anonymous visitors the usual flow (the login page) runs.
 */
export function createReauthenticate(
  queryClient: QueryClient,
  store: ReauthStore,
): () => Promise<ReauthOutcome> {
  return () =>
    queryClient.getQueryData(queryKeys.me) === undefined
      ? Promise.resolve("cancel")
      : store.request();
}
