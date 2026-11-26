import { ApiError, createApiClient } from "./client";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function call(mock: ReturnType<typeof vi.fn<typeof fetch>>): [string, RequestInit] {
  const first = mock.mock.calls[0];
  if (first === undefined) throw new Error("fetch was not called");
  const [input, init] = first;
  if (typeof input !== "string") throw new Error("expected a string URL");
  return [input, init ?? {}];
}

describe("api client", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const onUnauthorized = vi.fn();
  const client = createApiClient({ apiUrl: "/admin/api/v1", fetch: fetchMock, onUnauthorized });

  beforeEach(() => {
    fetchMock.mockReset();
    onUnauthorized.mockReset();
    document.cookie = "faststudio_csrftoken=tok123; path=/";
  });

  it("sends GET requests without a CSRF header, with credentials", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, { ok: true }));
    await expect(client.get("/meta")).resolves.toEqual({ ok: true });
    const [url, init] = call(fetchMock);
    expect(url).toBe("/admin/api/v1/meta");
    expect(init.credentials).toBe("same-origin");
    expect(new Headers(init.headers).has("x-faststudio-csrf")).toBe(false);
  });

  it.each(["post", "patch", "delete"] as const)(
    "sends the CSRF token from the cookie on %s",
    async (method) => {
      fetchMock.mockResolvedValueOnce(jsonResponse(200, {}));
      await client[method]("/x", method === "delete" ? undefined : { a: 1 });
      const [, init] = call(fetchMock);
      const headers = new Headers(init.headers);
      expect(headers.get("x-faststudio-csrf")).toBe("tok123");
      if (method !== "delete") {
        expect(headers.get("content-type")).toBe("application/json");
        expect(init.body).toBe(JSON.stringify({ a: 1 }));
      }
    },
  );

  it("returns undefined for 204 responses", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
    await expect(client.delete("/x")).resolves.toBeUndefined();
  });

  it("parses contract errors", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(422, {
        error: {
          code: "validation_error",
          message: "Invalid input.",
          details: [{ loc: ["title"], msg: "required", type: "missing" }],
        },
      }),
    );
    const error = await client.post("/x", {}).catch((e: unknown) => e);
    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({
      status: 422,
      code: "validation_error",
      message: "Invalid input.",
      details: [{ loc: ["title"], msg: "required", type: "missing" }],
    });
  });

  it("maps non-contract failures to internal_error", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>bad gateway</html>", { status: 502 }));
    await expect(client.get("/x")).rejects.toMatchObject({ status: 502, code: "internal_error" });
  });

  it("maps network failures to a network error", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    await expect(client.get("/x")).rejects.toMatchObject({ status: 0, code: "network_error" });
  });

  it("notifies on 401 not_authenticated", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, {
        error: { code: "not_authenticated", message: "Authentication required.", details: null },
      }),
    );
    await expect(client.get("/meta")).rejects.toMatchObject({ code: "not_authenticated" });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("does not treat a failed login as a session expiry", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(401, {
        error: { code: "invalid_credentials", message: "Invalid.", details: null },
      }),
    );
    await expect(client.post("/auth/login", {})).rejects.toMatchObject({
      code: "invalid_credentials",
    });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("encodes query params and skips undefined values", async () => {
    const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(new Response("{}", { status: 200 }));
    const api = createApiClient({ apiUrl: "/admin/api/v1", fetch: fetchMock });
    await api.get("/models/users/items", {
      params: { page: 2, q: "a&b=c", "filter[is_active]": "true", ordering: undefined },
    });
    const [url] = call(fetchMock);
    expect(url).toBe(
      "/admin/api/v1/models/users/items?page=2&q=a%26b%3Dc&filter%5Bis_active%5D=true",
    );
  });

  it("passes the abort signal and rethrows cancellations untouched", async () => {
    const controller = new AbortController();
    const abort = new DOMException("aborted", "AbortError");
    const fetchMock = vi.fn<typeof fetch>((_input, init) => {
      expect(init?.signal?.aborted).toBe(false);
      controller.abort();
      expect(init?.signal?.aborted).toBe(true); // the caller's signal is followed
      return Promise.reject(abort);
    });
    const api = createApiClient({ apiUrl: "/api", fetch: fetchMock });
    await expect(api.get("/x", { signal: controller.signal })).rejects.toBe(abort);
  });

  it("ends a session only after every request in flight settled (ADR-0013)", async () => {
    const events: string[] = [];
    let finishLogout: (response: Response) => void = () => undefined;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = input as string;
      events.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/auth/logout")) {
        return new Promise<Response>((resolve) => {
          finishLogout = resolve;
        });
      }
      if (url.endsWith("/later")) return Promise.resolve(jsonResponse(200, { ok: true }));
      return new Promise<Response>((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          events.push(`aborted ${url}`);
          reject(new DOMException("aborted", "AbortError"));
        });
      });
    });
    const api = createApiClient({ apiUrl: "/api", fetch: fetchMock });
    const read = api.get("/models/a/items");
    const write = api.patch("/models/a/items/1", { x: 1 });
    const logout = api.endSession("/auth/logout");
    // Not a network failure (no error toast, no retry): the session is ending.
    await expect(read).rejects.toMatchObject({ code: "session_ending" });
    await expect(write).rejects.toMatchObject({ code: "session_ending" });
    await vi.waitFor(() => {
      expect(events).toContain("POST /api/auth/logout");
    });
    // While the logout is on its way nothing else is sent (no retry, no click).
    await expect(api.get("/models/a/items")).rejects.toMatchObject({ code: "session_ending" });
    finishLogout(new Response(null, { status: 204 }));
    await expect(logout).resolves.toBeUndefined();
    expect(events).toEqual([
      "GET /api/models/a/items",
      "PATCH /api/models/a/items/1",
      "aborted /api/models/a/items",
      "aborted /api/models/a/items/1",
      "POST /api/auth/logout",
    ]);
    await expect(api.get("/later")).resolves.toEqual({ ok: true }); // open again
  });

  it("lets the admin sign in again when a password change meets an ended session", async () => {
    const sent: string[] = [];
    let signedIn = false;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = input as string;
      sent.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/auth/login")) {
        signedIn = true;
        return Promise.resolve(jsonResponse(200, { user: { id: "1", username: "a" } }));
      }
      return Promise.resolve(
        signedIn
          ? new Response(null, { status: 204 })
          : jsonResponse(401, { error: { code: "not_authenticated", message: "Sign in." } }),
      );
    });
    const onUnauthorized = vi.fn();
    const api = createApiClient({
      apiUrl: "/api",
      fetch: fetchMock,
      onUnauthorized,
      // The dialog: signs in through the same client while the change waits.
      reauthenticate: async () => {
        await api.post("/auth/login", { username: "a", password: "p" });
        return "retry";
      },
    });
    await expect(api.endSession("/auth/password", { x: 1 })).resolves.toBeUndefined();
    expect(sent).toEqual([
      "POST /api/auth/password",
      "POST /api/auth/login",
      "POST /api/auth/password",
    ]);
    expect(onUnauthorized).not.toHaveBeenCalled();
    await expect(api.get("/later")).resolves.toBeUndefined(); // the gate is open again
  });

  it("lets the sign-in through when a sign-out is queued behind a password change", async () => {
    // M20 follow-up N1: the queued sign-out used to keep the gate closed, so
    // the dialog's sign-in could never be sent.
    const sent: string[] = [];
    let signedIn = false;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = input as string;
      sent.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("/auth/login")) {
        signedIn = true;
        return Promise.resolve(jsonResponse(200, { user: { id: "1", username: "a" } }));
      }
      if (url.endsWith("/auth/logout")) return Promise.resolve(new Response(null, { status: 204 }));
      return Promise.resolve(
        signedIn
          ? new Response(null, { status: 204 })
          : jsonResponse(401, { error: { code: "not_authenticated", message: "Sign in." } }),
      );
    });
    let logout: Promise<unknown> = Promise.resolve();
    const api = createApiClient({
      apiUrl: "/api",
      fetch: fetchMock,
      reauthenticate: async () => {
        logout = api.endSession("/auth/logout"); // the admin clicked Sign out meanwhile
        await api.post("/auth/login", { username: "a", password: "p" });
        return "retry";
      },
    });
    await expect(api.endSession("/auth/password", { x: 1 })).resolves.toBeUndefined();
    await expect(logout).resolves.toBeUndefined();
    expect(sent).toEqual([
      "POST /api/auth/password",
      "POST /api/auth/login",
      "POST /api/auth/password",
      "POST /api/auth/logout",
    ]);
  });

  it("gives up a session-ending POST that never answers and reopens the gate", async () => {
    // M20 follow-up N2.
    const fetchMock = vi.fn<typeof fetch>(
      (input, init) =>
        new Promise<Response>((resolve, reject) => {
          if ((input as string).endsWith("/later")) {
            resolve(jsonResponse(200, { ok: true }));
            return;
          }
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("aborted", "AbortError"));
          });
        }),
    );
    const api = createApiClient({ apiUrl: "/api", fetch: fetchMock, sessionEndTimeoutMs: 20 });
    await expect(api.endSession("/auth/logout")).rejects.toMatchObject({
      code: "network_error",
      message: "The server did not answer.",
    });
    await expect(api.get("/later")).resolves.toEqual({ ok: true }); // the gate is open again
  });

  it("queues a second endSession instead of aborting the first", async () => {
    const sent: string[] = [];
    let finishFirst: (response: Response) => void = () => undefined;
    const fetchMock = vi.fn<typeof fetch>((input, init) => {
      const url = input as string;
      sent.push(url);
      if (url.endsWith("/auth/password")) {
        init?.signal?.addEventListener("abort", () => sent.push("aborted password"));
        return new Promise<Response>((resolve) => {
          finishFirst = resolve;
        });
      }
      return Promise.resolve(new Response(null, { status: 204 }));
    });
    const api = createApiClient({ apiUrl: "/api", fetch: fetchMock });
    const change = api.endSession("/auth/password", { x: 1 });
    const logout = api.endSession("/auth/logout");
    await vi.waitFor(() => {
      expect(sent).toEqual(["/api/auth/password"]);
    });
    finishFirst(new Response(null, { status: 204 }));
    await expect(change).resolves.toBeUndefined();
    await expect(logout).resolves.toBeUndefined();
    expect(sent).toEqual(["/api/auth/password", "/api/auth/logout"]);
  });
});
