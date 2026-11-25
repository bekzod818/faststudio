import { ApiError } from "./client";

/** The server refused the action for this admin (`403 forbidden`). */
export function isForbidden(error: unknown): boolean {
  return error instanceof ApiError && error.code === "forbidden";
}
