import type { DefaultOptions } from "@tanstack/react-query";

import { ApiError } from "@/api/client";

/** Retry transient failures once; a 4xx answer will not change on retry. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}

/**
 * The QueryClient defaults. No background refetching (no polling, no refetch
 * on window focus): with `session_idle_timeout` only real use may keep a
 * session alive (ADR-0013). A test pins this.
 */
export const QUERY_DEFAULTS = {
  queries: { retry: shouldRetry, refetchOnWindowFocus: false, refetchInterval: false },
  mutations: { retry: false },
} satisfies DefaultOptions;
