import { ApiError } from "@/api/client";

/** Retry transient failures once; a 4xx answer will not change on retry. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 1;
}
