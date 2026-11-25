import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { toast } from "@/lib/toast";

import { App } from "./App";
import { shouldRetry } from "./query";

const CONFIG = {
  schemaVersion: "1",
  baseUrl: "/admin",
  apiUrl: "/admin/api/v1",
  title: "Test Admin",
  maxListOffset: 10_000,
} as const;

const ME = { user: { id: "1", username: "admin" } };
function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

const NOT_AUTHENTICATED = { error: { code: "not_authenticated", message: "Sign in." } };

describe("App", () => {
  let routes: Record<string, () => Response>;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    routes = {};
    fetchMock = vi.fn((input: string) => {
      const path = input.replace(/^\/admin\/api\/v1/u, "");
      const handler = routes[path];
      return Promise.resolve(
        handler ? handler() : json(404, { error: { code: "not_found", message: "x" } }),
      );
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    toast.clear();
    window.history.replaceState(null, "", "/");
  });

  it("sends anonymous visitors to login once, without a toast", async () => {
    routes["/auth/me"] = () => json(401, NOT_AUTHENTICATED);
    window.history.replaceState(null, "", "/admin/models/users");
    render(<App config={CONFIG} />);
    expect(await screen.findByRole("heading", { name: "Test Admin" })).toBeVisible();
    expect(window.location.pathname).toBe("/admin/login");
    expect(new URLSearchParams(window.location.search).get("next")).toBe("/models/users");
    expect(fetchMock).toHaveBeenCalledTimes(1); // a 401 is not retried
    expect(screen.queryByText(/session has ended/i)).toBeNull();
  });

  it.each([true, false])(
    "links to the password page only when the backend offers it (%s)",
    async (offered) => {
      routes["/auth/me"] = () => json(200, ME);
      routes["/meta"] = () =>
        json(200, {
          schema_version: "1",
          version: "0",
          title: "Test Admin",
          show_powered_by: true,
          user: ME.user,
          models: [],
          capabilities: { change_password: offered, sign_out_everywhere: false },
        });
      window.history.replaceState(null, "", "/admin/");
      render(<App config={CONFIG} />);
      expect(await screen.findByRole("button", { name: "Sign out" })).toBeVisible();
      await waitFor(() => {
        expect(screen.queryByRole("link", { name: "Change password" }) !== null).toBe(offered);
      });
    },
  );

  it("returns an expired session to login with the in-app path", async () => {
    routes["/auth/me"] = () => json(200, ME);
    routes["/meta"] = () => json(401, NOT_AUTHENTICATED);
    window.history.replaceState(null, "", "/admin/models/users");
    render(<App config={CONFIG} />);
    expect(await screen.findByText(/session has ended/i)).toBeVisible();
    await waitFor(() => {
      expect(window.location.pathname).toBe("/admin/login");
    });
    expect(new URLSearchParams(window.location.search).get("next")).toBe("/models/users");
  });
});

describe("shouldRetry", () => {
  it("never retries client errors", () => {
    expect(shouldRetry(0, new ApiError(404, "not_found", "x"))).toBe(false);
  });

  it("retries other failures once", () => {
    const network = new ApiError(0, "network_error", "x");
    expect(shouldRetry(0, network)).toBe(true);
    expect(shouldRetry(1, network)).toBe(false);
  });
});
