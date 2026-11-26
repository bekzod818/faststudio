import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import { getToasts, toast } from "@/lib/toast";

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
  /** Paths whose response never arrives; aborting rejects them (logged in `events`). */
  let hanging: Set<string>;
  let events: string[];
  let fetchMock: ReturnType<typeof vi.fn<(input: string, init?: RequestInit) => Promise<Response>>>;

  beforeEach(() => {
    routes = {};
    hanging = new Set();
    events = [];
    fetchMock = vi.fn((input: string, init?: RequestInit) => {
      const path = input.replace(/^\/admin\/api\/v1/u, "");
      events.push(`${init?.method ?? "GET"} ${path}`);
      if (hanging.has(path)) {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            events.push(`aborted ${path}`);
            reject(new DOMException("aborted", "AbortError"));
          });
        });
      }
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

  const metaWith = (signOutEverywhere: boolean) => () =>
    json(200, {
      schema_version: "1",
      version: "0",
      title: "Test Admin",
      show_powered_by: true,
      user: ME.user,
      models: [],
      capabilities: { change_password: false, sign_out_everywhere: signOutEverywhere },
    });

  it.each([true, false])(
    "offers sign out everywhere only when the backend does (%s)",
    async (offered) => {
      routes["/auth/me"] = () => json(200, ME);
      routes["/meta"] = metaWith(offered);
      window.history.replaceState(null, "", "/admin/");
      render(<App config={CONFIG} />);
      expect(await screen.findByRole("button", { name: "Sign out" })).toBeVisible();
      await waitFor(() => {
        expect(screen.queryByRole("button", { name: "Sign out everywhere" }) !== null).toBe(
          offered,
        );
      });
    },
  );

  it("aborts requests in flight before signing out (a late one could renew the session)", async () => {
    routes["/auth/me"] = () => json(200, ME);
    routes["/auth/logout"] = () => new Response(null, { status: 204 });
    hanging.add("/meta"); // e.g. a slow read still running when Sign out is clicked
    window.history.replaceState(null, "", "/admin/");
    render(<App config={CONFIG} />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    await waitFor(() => {
      expect(window.location.pathname).toBe("/admin/login");
    });
    const logout = events.indexOf("POST /auth/logout");
    expect(logout).toBeGreaterThan(-1);
    expect(events.indexOf("aborted /meta")).toBeGreaterThan(-1);
    expect(events.indexOf("aborted /meta")).toBeLessThan(logout);
  });

  it("signs out everywhere after confirmation", async () => {
    routes["/auth/me"] = () => json(200, ME);
    routes["/meta"] = metaWith(true);
    routes["/auth/sign-out-everywhere"] = () => new Response(null, { status: 204 });
    window.history.replaceState(null, "", "/admin/");
    render(<App config={CONFIG} />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign out everywhere" }));
    const dialog = await screen.findByRole("dialog", { name: "Sign out everywhere?" });
    expect(dialog).toHaveTextContent(/every browser and on every device/u);
    const posted = () =>
      fetchMock.mock.calls.filter(([url]) => url.endsWith("/auth/sign-out-everywhere"));
    // Cancelling sends nothing.
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(posted()).toHaveLength(0);
    await userEvent.click(screen.getByRole("button", { name: "Sign out everywhere" }));
    await userEvent.click(
      within(await screen.findByRole("dialog", { name: "Sign out everywhere?" })).getByRole(
        "button",
        { name: "Sign out everywhere" },
      ),
    );
    await waitFor(() => {
      expect(window.location.pathname).toBe("/admin/login");
    });
    expect(posted()).toHaveLength(1);
    expect((posted()[0]?.[1] as RequestInit).method).toBe("POST");
    expect(getToasts().map((t) => t.message)).toContain("Signed out on every device.");
  });

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
