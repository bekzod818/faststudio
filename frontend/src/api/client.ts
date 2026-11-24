import type { ErrorCode, ValidationIssue } from "./contract.gen";
import { readCookie } from "@/lib/cookies";

export const CSRF_COOKIE = "faststudio_csrftoken";
export const CSRF_HEADER = "X-FastStudio-CSRF";

/** Client-side codes in addition to the server's `ErrorCode`s. */
export type ClientErrorCode = ErrorCode | "network_error";

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
}

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

  async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    { params, signal }: GetOptions = {},
  ): Promise<T> {
    const headers = new Headers({ accept: "application/json" });
    if (method !== "GET") {
      const token = readCookie(CSRF_COOKIE);
      if (token !== undefined) headers.set(CSRF_HEADER, token);
    }
    const init: RequestInit = { method, headers, credentials: "same-origin" };
    if (signal !== undefined) init.signal = signal;
    if (body !== undefined) {
      headers.set("content-type", "application/json");
      init.body = JSON.stringify(body);
    }
    let response: Response;
    try {
      response = await doFetch(`${options.apiUrl}${path}${queryString(params)}`, init);
    } catch (error) {
      // Let TanStack Query recognise its own cancellations.
      if (signal?.aborted) throw error;
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
      if (response.status === 401 && code === "not_authenticated") options.onUnauthorized?.();
      throw new ApiError(response.status, code, message, details);
    }
    throw new ApiError(response.status, "internal_error", "Unexpected server response.");
  }

  return {
    get: (path, getOptions) => request("GET", path, undefined, getOptions),
    post: (path, body) => request("POST", path, body),
    patch: (path, body) => request("PATCH", path, body),
    delete: (path) => request("DELETE", path),
  };
}
