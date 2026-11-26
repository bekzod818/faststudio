import { QueryClient } from "@tanstack/react-query";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, createApiClient, type ReauthOutcome } from "@/api/client";
import type { MetaResponse, Row } from "@/api/contract.gen";
import { queryKeys } from "@/api/hooks";
import { CreateRoute, RecordRoute } from "@/features/record/RecordPages";
import { getToasts, toast } from "@/lib/toast";
import { testModel } from "@/test/fixtures";
import { renderRoutes } from "@/test/render";

import { createReauthStore } from "./reauth";
import { ReauthDialog } from "./ReauthDialog";

const ME = { user: { id: "1", username: "admin" } };
const NOT_AUTHENTICATED = { error: { code: "not_authenticated", message: "Sign in." } };
const INVALID = {
  error: { code: "invalid_credentials", message: "Invalid username or password." },
};

function json(status: number, body: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

afterEach(() => {
  toast.clear();
});

describe("reauth store", () => {
  it("shares one request between concurrent writes", async () => {
    const store = createReauthStore();
    const listener = vi.fn();
    store.subscribe(listener);
    expect(store.isOpen()).toBe(false);
    const first = store.request();
    const second = store.request();
    expect(first).toBe(second);
    expect(store.isOpen()).toBe(true);
    store.settle("retry");
    await expect(first).resolves.toBe("retry");
    expect(store.isOpen()).toBe(false);
    expect(listener).toHaveBeenCalledTimes(2);
  });
});

describe("api client on a 401 during a write", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const onUnauthorized = vi.fn();
  const reauthenticate = vi.fn<() => Promise<ReauthOutcome>>();
  const client = createApiClient({
    apiUrl: "/api",
    fetch: fetchMock,
    onUnauthorized,
    reauthenticate,
  });

  beforeEach(() => {
    fetchMock.mockReset();
    onUnauthorized.mockReset();
    reauthenticate.mockReset();
  });

  it("resends the same body once after the same account signs in", async () => {
    document.cookie = "faststudio_csrftoken=old; path=/";
    fetchMock
      .mockResolvedValueOnce(json(401, NOT_AUTHENTICATED))
      .mockResolvedValueOnce(json(200, { pk: "7" }));
    reauthenticate.mockImplementation(() => {
      document.cookie = "faststudio_csrftoken=new; path=/"; // set by the login response
      return Promise.resolve("retry");
    });
    await expect(client.patch("/models/users/items/7", { email: "b@x" })).resolves.toEqual({
      pk: "7",
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [, retry] = fetchMock.mock.calls[1] ?? [];
    expect(retry?.body).toBe(JSON.stringify({ email: "b@x" }));
    expect(new Headers(retry?.headers).get("x-faststudio-csrf")).toBe("new");
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("gives up after one retry", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(json(401, NOT_AUTHENTICATED)));
    reauthenticate.mockResolvedValue("retry");
    await expect(client.post("/models/users/items", {})).rejects.toBeInstanceOf(ApiError);
    expect(reauthenticate).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it("drops the write quietly when another account signed in", async () => {
    fetchMock.mockResolvedValueOnce(json(401, NOT_AUTHENTICATED));
    reauthenticate.mockResolvedValue("discard");
    await expect(client.delete("/models/users/items/7")).rejects.toMatchObject({ status: 401 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("ends the session as usual when the admin cancels", async () => {
    fetchMock.mockResolvedValueOnce(json(401, NOT_AUTHENTICATED));
    reauthenticate.mockResolvedValue("cancel");
    await expect(client.post("/auth/password", {})).rejects.toBeInstanceOf(ApiError);
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["get", "/meta"],
    ["post", "/auth/login"],
    ["post", "/auth/logout"],
    ["post", "/auth/sign-out-everywhere"],
  ] as const)("never asks for %s %s", async (method, path) => {
    fetchMock.mockResolvedValueOnce(json(401, NOT_AUTHENTICATED));
    await expect(client[method](path)).rejects.toBeInstanceOf(ApiError);
    expect(reauthenticate).not.toHaveBeenCalled();
    expect(onUnauthorized).toHaveBeenCalledTimes(1);
  });
});

// ------------------------------------------------------------------ the form

const ROW: Row = {
  pk: "7",
  data: { id: 7, email: "ann@example.com", is_active: true, status: "TODO", team_id: 1 },
  labels: { team_id: "Core" },
  many_labels: {},
  truncated: [],
};

const META: MetaResponse = {
  schema_version: "1",
  version: "0",
  title: "Admin",
  show_powered_by: true,
  user: ME.user,
  capabilities: { change_password: false, sign_out_everywhere: false },
  models: [testModel()],
};

function setupForm(login: () => Response, path = "/models/users/items/7") {
  const sent: { method: string; path: string; body: unknown }[] = [];
  let expired = true;
  const fetchMock = vi.fn((input: string, init?: RequestInit) => {
    const url = input.replace(/^\/api/u, "").split("?")[0] ?? "";
    const method = init?.method ?? "GET";
    const body: unknown = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    sent.push({ method, path: url, body });
    if (method === "GET") {
      if (url === "/meta") return Promise.resolve(json(200, META));
      if (url === "/models/users/items/7") return Promise.resolve(json(200, ROW));
      return Promise.resolve(json(200, { items: [], has_more: false }));
    }
    if (url === "/auth/login") {
      const response = login();
      if (response.ok) expired = false;
      return Promise.resolve(response);
    }
    if (expired) return Promise.resolve(json(401, NOT_AUTHENTICATED));
    return Promise.resolve(json(200, { ...ROW, data: { ...ROW.data, ...(body as object) } }));
  });
  const store = createReauthStore();
  const onUnauthorized = vi.fn();
  const client = createApiClient({
    apiUrl: "/api",
    fetch: fetchMock as unknown as typeof fetch,
    onUnauthorized,
    reauthenticate: store.request,
  });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  queryClient.setQueryData(queryKeys.me, ME);
  type Navigate = (to: string, options: { replace: boolean; state: unknown }) => Promise<void>;
  let navigate: Navigate = () => Promise.resolve();
  const dialog = (
    <ReauthDialog store={store} router={() => ({ navigate: (...a) => navigate(...a) })} />
  );
  const result = renderRoutes(
    [
      {
        path: "/models/:identity/items/:pk",
        element: (
          <>
            <RecordRoute />
            {dialog}
          </>
        ),
      },
      {
        path: "/models/:identity/new",
        element: (
          <>
            <CreateRoute />
            {dialog}
          </>
        ),
      },
      { path: "/", element: <p>Dashboard</p> },
    ],
    { client, path, queryClient },
  );
  navigate = (to, options) => result.router.navigate(to, options);
  return { ...result, sent, onUnauthorized, store };
}

async function editAndSave() {
  const email = await screen.findByLabelText(/Email/);
  await userEvent.clear(email);
  await userEvent.type(email, "bob@example.com");
  await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
  return email;
}

describe("a save that meets an ended session", () => {
  it("asks to sign in in place and saves the original input", async () => {
    const { sent, onUnauthorized, queryClient } = setupForm(() => json(200, ME));
    const email = await editAndSave();
    const dialog = await screen.findByRole("dialog", { name: "Sign in to continue" });
    expect(dialog).toBeVisible();
    expect(screen.getByLabelText("Username")).toHaveValue("admin");
    expect(email).toHaveValue("bob@example.com"); // still on the page, untouched
    await userEvent.type(screen.getByLabelText("Password"), "secret passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Sign in and save" }));
    await waitFor(() => {
      expect(getToasts().map((t) => t.message)).toContain("Changes saved.");
    });
    const writes = sent.filter((s) => s.method !== "GET");
    expect(writes).toEqual([
      { method: "PATCH", path: "/models/users/items/7", body: { email: "bob@example.com" } },
      {
        method: "POST",
        path: "/auth/login",
        body: { username: "admin", password: "secret passphrase" },
      },
      { method: "PATCH", path: "/models/users/items/7", body: { email: "bob@example.com" } },
    ]);
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(queryKeys.me)).toEqual(ME);
    expect(screen.queryByRole("dialog")).toBeNull();
    // Nothing of the form ever reaches browser storage.
    expect(window.localStorage.length).toBe(0);
    expect(window.sessionStorage.length).toBe(0);
  });

  it("keeps the dialog open after a wrong password, without the password", async () => {
    let attempts = 0;
    setupForm(() => (++attempts === 1 ? json(401, INVALID) : json(200, ME)));
    await editAndSave();
    await screen.findByRole("dialog", { name: "Sign in to continue" });
    const password = screen.getByLabelText("Password");
    await userEvent.type(password, "wrong");
    await userEvent.click(screen.getByRole("button", { name: "Sign in and save" }));
    expect(await screen.findByText("Invalid username or password.")).toBeVisible();
    expect(password).toHaveValue("");
    await userEvent.type(password, "right one");
    await userEvent.click(screen.getByRole("button", { name: "Sign in and save" }));
    await waitFor(() => {
      expect(getToasts().map((t) => t.message)).toContain("Changes saved.");
    });
  });

  it("discards the input when another account signs in", async () => {
    const other = { user: { id: "2", username: "bob" } };
    const { sent, router, queryClient, onUnauthorized } = setupForm(() => json(200, other));
    await editAndSave();
    await screen.findByRole("dialog", { name: "Sign in to continue" });
    await userEvent.clear(screen.getByLabelText("Username"));
    await userEvent.type(screen.getByLabelText("Username"), "bob");
    await userEvent.type(screen.getByLabelText("Password"), "bob's passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Sign in and save" }));
    expect(await screen.findByText("Dashboard")).toBeVisible();
    expect(router.state.location.pathname).toBe("/");
    expect(sent.filter((s) => s.method === "PATCH")).toHaveLength(1); // never resent
    expect(queryClient.getQueryData(queryKeys.me)).toEqual(other);
    expect(queryClient.getQueryData(queryKeys.item("users", "7"))).toBeUndefined();
    expect(onUnauthorized).not.toHaveBeenCalled();
    expect(getToasts().map((t) => t.message)).toContain(
      "Signed in as bob. The unsaved changes were discarded.",
    );
  });

  it("falls back to the usual sign-out when the admin discards", async () => {
    const { onUnauthorized, sent } = setupForm(() => json(200, ME));
    await editAndSave();
    await screen.findByRole("dialog", { name: "Sign in to continue" });
    await userEvent.click(screen.getByRole("button", { name: "Discard changes" }));
    await waitFor(() => {
      expect(onUnauthorized).toHaveBeenCalledTimes(1);
    });
    expect(sent.some((s) => s.path === "/auth/login")).toBe(false);
  });

  it("also covers creating a record", async () => {
    const { sent } = setupForm(() => json(200, ME), "/models/users/new");
    await userEvent.type(await screen.findByLabelText(/Email/), "new@example.com");
    await userEvent.click(screen.getByRole("button", { name: /Create/ }));
    await screen.findByRole("dialog", { name: "Sign in to continue" });
    await userEvent.type(screen.getByLabelText("Password"), "secret passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Sign in and save" }));
    await waitFor(() => {
      expect(
        sent.filter((s) => s.method === "POST" && s.path === "/models/users/items"),
      ).toHaveLength(2);
    });
    const [first, second] = sent.filter(
      (s) => s.path === "/models/users/items" && s.method === "POST",
    );
    expect(second?.body).toEqual(first?.body);
  });
});
