/**
 * Return `next` if it is a safe in-app path (router-relative), else "/".
 *
 * Prevents open redirects through `/login?next=...`: only single-slash
 * absolute paths without backslashes, control characters or a scheme are
 * accepted, and never the login page itself.
 */
import { hasForbiddenCharacters } from "./text";

export function safeNext(next: string | null | undefined): string {
  if (!next || !next.startsWith("/") || next.startsWith("//")) return "/";
  if (next.includes("\\") || hasForbiddenCharacters(next)) return "/";
  if (/%0[0-9a-f]|%1[0-9a-f]|%7f/iu.test(next)) return "/";
  let decoded: string;
  try {
    decoded = decodeURIComponent(next);
  } catch {
    return "/";
  }
  if (decoded.includes("\\") || hasForbiddenCharacters(decoded)) return "/";
  if (isLoginPath(decoded)) return "/";
  return next;
}

/** The router matches case-insensitively and ignores trailing slashes. */
function isLoginPath(next: string): boolean {
  const path = (next.split(/[?#]/u, 1)[0] ?? "").toLowerCase().replace(/\/+$/u, "");
  return path === "/login";
}
