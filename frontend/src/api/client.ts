import type { ErrorCode, ValidationIssue } from "./contract.gen";
import { readCookie } from "@/lib/cookies";

export const CSRF_COOKIE = "faststudio_csrftoken";
export const CSRF_HEADER = "X-FastStudio-CSRF";

/**
 * What to do with a write that met `401 not_authenticated` after asking the
 * admin to sign in again: `retry` (same account), `discard` (another
 * account signed in) or `cancel` (the usual "session ended" flow).
 */
export type ReauthOutcome = "retry" | "discard" | "cancel";

/** Client-side codes in addition to the server's `ErrorCode`s. */
export type ClientErrorCode = ErrorCode | "network_error" | "session_ending";

/** A failed API call, carrying the contract's error body. */
export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: ClientErrorCode,
    message: string,
    readonly details: ValidationIssue[] | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface ApiClientOptions {
  apiUrl: string;
  fetch?: typeof fetch;
  /** Called once per `401 not_authenticated` (expired or revoked session). */
  onUnauthorized?: () => void;
  /**
   * Asked when a write gets `401 not_authenticated`: `retry` resends it once,
   * `discard` fails it quietly, `cancel` runs `onUnauthorized`.
   */
  reauthenticate?: () => Promise<ReauthOutcome>;
}

/** Query parameters; `undefined` values are skipped. */
export type QueryParams = Record<string, string | number | undefined>;

export interface GetOptions {
  params?: QueryParams;
  /** Cancels the request (TanStack Query passes one to every queryFn). */
  signal?: AbortSignal;
}

export interface ApiClient {
  get<T>(path: string, options?: GetOptions): Promise<T>;
  post<T>(path: string, body?: unknown): Promise<T>;
  patch<T>(path: string, body?: unknown): Promise<T>;
  delete<T = undefined>(path: string): Promise<T>;
  /**
   * POST a request that ends or replaces the session (logout, sign out
   * everywhere, a password change). With `session_idle_timeout` any response
   * may renew the session cookie, and a late one must not bring the session
   * back, so: every request in flight is aborted and awaited first, and until
   * this POST settles every other request fails at once without being sent
   * (`network_error`). Callers cancel their query retries first.
   */
  endSession<T = undefined>(path: string, body?: unknown): Promise<T>;
}

/** Writes that start or end a session: a 401 there is never retried. */
export const LOGIN_PATH = "/auth/login";
export const LOGOUT_PATH = "/auth/logout";
export const SIGN_OUT_EVERYWHERE_PATH = "/auth/sign-out-everywhere";
export const PASSWORD_PATH = "/auth/password";
const SESSION_PATHS = new Set([LOGIN_PATH, LOGOUT_PATH, SIGN_OUT_EVERYWHERE_PATH]);

function isErrorBody(
  value: unknown,
): value is { error: { code: ErrorCode; message: string; details: ValidationIssue[] | null } } {
  if (typeof value !== "object" || value === null || !("error" in value)) return false;
  const error = value.error;
  return (
    typeof error === "object" &&
    error !== null &&
    typeof (error as { code?: unknown }).code === "string" &&
    typeof (error as { message?: unknown }).message === "string"
  );
}

function queryString(params: QueryParams | undefined): string {
  if (params === undefined) return "";
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.append(key, String(value));
  }
  const text = search.toString();
  return text === "" ? "" : `?${text}`;
}

/**
 * Create the JSON API client.
 *
 * Every unsafe request carries the CSRF token from the `faststudio_csrftoken`
 * cookie (double submit); cookies are sent only to the same origin.
 */
export function createApiClient(options: ApiClientOptions): ApiClient {
  const doFetch = options.fetch ?? globalThis.fetch.bind(globalThis);
  const inFlight = new Map<AbortController, Promise<unknown>>();
  let closing = 0;
  /** The previous endSession(): a second one waits instead of aborting its POST. */
  let ending: Promise<unknown> = Promise.resolve();

  /** Abort every request in flight and wait until each has settled. */
  async function drain(): Promise<void> {
    const settling = [...inFlight].map(([controller, settled]) => {
      controller.abort();
      return settled;
    });
    await Promise.all(settling);
  }

  /** Fetch with our own abort controller, also following the caller's signal. */
  function tracked(url: string, init: RequestInit, signal: AbortSignal | undefined) {
    const controller = new AbortController();
    const follow = () => {
      controller.abort(signal?.reason);
    };
    if (signal?.aborted === true) follow();
    else signal?.addEventListener("abort", follow, { once: true });
    const pending = doFetch(url, { ...init, signal: controller.signal });
    const settled = pending.then(
      () => undefined,
      () => undefined,
    );
    inFlight.set(controller, settled);
    void settled.then(() => {
      inFlight.delete(controller);
      signal?.removeEventListener("abort", follow);
    });
    return { pending, aborted: () => controller.signal.aborted };
  }

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    getOptions: GetOptions = {},
    retried = false,
    endingSession = false,
  ): Promise<T> {
    const { params, signal } = getOptions;
    if (closing > 0 && !endingSession) {
      // Nothing may reach the server (and renew the cookie) while the session ends.
      throw new ApiError(0, "session_ending", "The session is ending.");
    }
    const headers = new Headers({ accept: "application/json" });
    if (method !== "GET") {
      const token = readCookie(CSRF_COOKIE);
      if (token !== undefined) headers.set(CSRF_HEADER, token);
    }
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (body !== undefined) {
      headers.set("content-type", "application/json");
      init.body = JSON.stringify(body);
    }
    let response: Response;
    const call = tracked(`${options.apiUrl}${path}${queryString(params)}`, init, signal);
    try {
      response = await call.pending;
    } catch (error) {
      // Let TanStack Query recognise its own cancellations.
      if (signal?.aborted) throw error;
      // Aborted by endSession(): neither a network failure nor worth a retry.
      if (call.aborted()) throw new ApiError(0, "session_ending", "The session is ending.");
      throw new ApiError(0, "network_error", "The server could not be reached.");
    }
    if (response.status === 204) return undefined as T;
    let payload: unknown;
    try {
      payload = await response.json();
    } catch {
      payload = null;
    }
    if (response.ok) return payload as T;
    if (isErrorBody(payload)) {
      const { code, message, details } = payload.error;
      const error = new ApiError(response.status, code, message, details);
      if (response.status === 401 && code === "not_authenticated") {
        const reauthenticate = options.reauthenticate;
        if (method !== "GET" && !retried && !SESSION_PATHS.has(path) && reauthenticate) {
          // A session-ending write (a password change) holds the gate: open it
          // while the admin signs in again, or the sign-in could not be sent.
          if (endingSession) closing -= 1;
          let outcome: ReauthOutcome;
          try {
            outcome = await reauthenticate();
          } finally {
            if (endingSession) closing += 1;
          }
          // The new sign-in set a new CSRF cookie: the retry reads it.
          if (outcome === "retry") {
            if (endingSession) await drain(); // what started meanwhile must not race it
            return request<T>(method, path, body, getOptions, true, endingSession);
          }
          if (outcome === "discard") throw error;
        }
        options.onUnauthorized?.();
      }
      throw error;
    }
    throw new ApiError(response.status, "internal_error", "Unexpected server response.");
  }

  return {
    get: (path, getOptions) => request("GET", path, undefined, getOptions),
    post: (path, body) => request("POST", path, body),
    patch: (path, body) => request("PATCH", path, body),
    delete: (path) => request("DELETE", path),
    endSession: <T>(path: string, body?: unknown): Promise<T> => {
      closing += 1;
      const run = ending.then(async () => {
        try {
          await drain();
          return await request<T>("POST", path, body, {}, false, true);
        } finally {
          closing -= 1;
        }
      });
      ending = run.catch(() => undefined);
      return run;
    },
  };
}
