import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, type ApiClient } from "@/api/client";
import type { MetaResponse, ModelMeta, Row } from "@/api/contract.gen";
import { ModelListRoute } from "@/features/list/ListPage";
import { getToasts, toast } from "@/lib/toast";
import { SKIP_GUARD, hasUnsavedChanges } from "@/lib/unsaved";
import { testField, testModel } from "@/test/fixtures";
import { fakeClient, renderRoutes } from "@/test/render";

import { CreateRoute, RecordRoute } from "./RecordPages";

function model(overrides: Partial<ModelMeta> = {}): ModelMeta {
  const base = testModel();
  return {
    ...base,
    fields: base.fields.map((field) =>
      field.name === "email" ? testField({ ...field, required: true, max_length: 50 }) : field,
    ),
    ...overrides,
  };
}

const ROW: Row = {
  pk: "7",
  data: { id: 7, email: "ann@example.com", is_active: true, status: "TODO", team_id: 1 },
  labels: { team_id: "Core" },
};

const routes = [
  { path: "/models/:identity", element: <ModelListRoute /> },
  { path: "/models/:identity/new", element: <CreateRoute /> },
  { path: "/models/:identity/items/:pk", element: <RecordRoute /> },
];

function setup(
  path: string,
  options: { meta?: ModelMeta; client?: Partial<ApiClient>; row?: Row } = {},
) {
  const row = options.row ?? ROW;
  const meta: MetaResponse = {
    schema_version: "1",
    version: "0",
    title: "Admin",
    show_powered_by: true,
    user: { id: "1", username: "admin" },
    models: [options.meta ?? model()],
  };
  const get = vi.fn((url: string) => {
    if (url === "/meta") return Promise.resolve(meta);
    if (url === `/models/users/items/${row.pk}`) return Promise.resolve(row);
    if (url === "/models/users/items")
      return Promise.resolve({ items: [ROW], total: 1, page: 1, page_size: 2 });
    return Promise.reject(new ApiError(404, "not_found", "Not found."));
  });
  const client = fakeClient({ get: get as unknown as ApiClient["get"], ...options.client });
  return { ...renderRoutes(routes, { client, path }), get };
}

afterEach(() => {
  toast.clear();
});

describe("create", () => {
  it("shows only writable fields and validates before sending", async () => {
    const post = vi.fn();
    setup("/models/users/new", { client: { post } });
    expect(await screen.findByRole("heading", { name: "Add user" })).toBeVisible();
    expect(screen.queryByLabelText("ID")).toBeNull(); // readonly primary key
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByText("This field is required.")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Please fix the highlighted fields.");
    expect(screen.getByLabelText(/Email/)).toHaveFocus();
    expect(screen.getByLabelText(/Email/)).toHaveAttribute("aria-invalid", "true");
    expect(post).not.toHaveBeenCalled();
  });

  it("sends the typed values and opens the new record", async () => {
    const post = vi.fn().mockResolvedValue(ROW);
    const { router } = setup("/models/users/new", { client: { post } });
    await userEvent.type(await screen.findByLabelText(/Email/), "ann@example.com");
    await userEvent.click(screen.getByLabelText("Is active"));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "Done");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/models/users/items/7");
    });
    expect(post).toHaveBeenCalledWith("/models/users/items", {
      email: "ann@example.com",
      is_active: true,
      status: "DONE",
    });
    expect(getToasts().map((t) => t.message)).toContain("User created.");
  });

  it("shows server validation errors next to their fields", async () => {
    const post = vi.fn().mockRejectedValue(
      new ApiError(422, "validation_error", "Invalid input.", [
        { loc: ["email"], msg: "Value already used", type: "value_error" },
        { loc: ["body"], msg: "Something else.", type: "x" },
      ]),
    );
    setup("/models/users/new", { client: { post } });
    await userEvent.type(await screen.findByLabelText(/Email/), "ann@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Create user" }));
    expect(await screen.findByText("Value already used")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Something else.");
    // Editing the field clears its error.
    await userEvent.type(screen.getByLabelText(/Email/), "x");
    expect(screen.queryByText("Value already used")).toBeNull();
  });

  it("explains when creating is disabled", async () => {
    setup("/models/users/new", {
      meta: model({ permissions: { create: false, edit: true, delete: true } }),
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Adding users is disabled.");
    expect(screen.queryByRole("button", { name: /Create/ })).toBeNull();
  });
});

describe("edit", () => {
  it("loads the record and sends only changed fields", async () => {
    const patch = vi
      .fn()
      .mockResolvedValue({ ...ROW, data: { ...ROW.data, email: "bob@example.com" } });
    setup("/models/users/items/7", { client: { patch } });
    const email = await screen.findByLabelText(/Email/);
    expect(email).toHaveValue("ann@example.com");
    expect(screen.getByLabelText("ID")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Team" })).toHaveValue("Core");
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(save).toBeDisabled();
    await userEvent.clear(email);
    await userEvent.type(email, "bob@example.com");
    await userEvent.click(save);
    await waitFor(() => {
      expect(patch).toHaveBeenCalledWith("/models/users/items/7", { email: "bob@example.com" });
    });
    expect(getToasts().map((t) => t.message)).toContain("Changes saved.");
    await waitFor(() => {
      expect(screen.getByRole("button", { name: "Save changes" })).toBeDisabled();
    });
  });

  it("is read-only when editing is disabled", async () => {
    setup("/models/users/items/7", {
      meta: model({ permissions: { create: true, edit: false, delete: false } }),
    });
    expect(await screen.findByLabelText(/Email/)).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save changes" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
  });

  it("shows not found for a missing record", async () => {
    setup("/models/users/items/404");
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeVisible();
  });
});

describe("delete", () => {
  it("asks for confirmation, deletes and returns to the list", async () => {
    const del = vi.fn().mockResolvedValue(undefined);
    const { router, get } = setup("/models/users/items/7", { client: { delete: del } });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    const dialog = screen.getByRole("dialog", { name: "Delete User 7?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(del).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/models/users");
    });
    expect(del).toHaveBeenCalledWith("/models/users/items/7");
    expect(getToasts().map((t) => t.message)).toContain("User 7 deleted.");
    // The deleted record is never fetched again (that would 404).
    expect(get.mock.calls.filter(([url]) => url === "/models/users/items/7")).toHaveLength(1);
  });

  it("reports a refused delete and stays on the record", async () => {
    const del = vi
      .fn()
      .mockRejectedValue(new ApiError(409, "conflict", "Cannot delete: related records exist."));
    const { router } = setup("/models/users/items/7", { client: { delete: del } });
    await userEvent.click(await screen.findByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() => {
      expect(getToasts().map((t) => t.message)).toContain("Cannot delete: related records exist.");
    });
    expect(router.state.location.pathname).toBe("/models/users/items/7");
  });
});

describe("unsaved changes", () => {
  it("asks before leaving and can stay or discard", async () => {
    const { router } = setup("/models/users/items/7");
    await userEvent.type(await screen.findByLabelText(/Email/), "x");
    await userEvent.click(screen.getByRole("link", { name: "Users" }));
    const dialog = await screen.findByRole("dialog", { name: "Leave this page?" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Stay" }));
    expect(router.state.location.pathname).toBe("/models/users/items/7");
    expect(screen.getByLabelText(/Email/)).toHaveValue("ann@example.comx");
    await userEvent.click(screen.getByRole("link", { name: "Users" }));
    await userEvent.click(
      within(await screen.findByRole("dialog", { name: "Leave this page?" })).getByRole("button", {
        name: "Discard changes",
      }),
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/models/users");
    });
  });
});

describe("guard exceptions", () => {
  it("deleting a record with unsaved edits goes straight to the list", async () => {
    const del = vi.fn().mockResolvedValue(undefined);
    const { router } = setup("/models/users/items/7", { client: { delete: del } });
    await userEvent.type(await screen.findByLabelText(/Email/), "x");
    expect(hasUnsavedChanges()).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }),
    );
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/models/users");
    });
    expect(screen.queryByRole("dialog", { name: "Leave this page?" })).toBeNull();
    expect(hasUnsavedChanges()).toBe(false); // the form unmounted
  });

  it("auth redirects pass the guard (the session is gone)", async () => {
    const { router } = setup("/models/users/items/7");
    await userEvent.type(await screen.findByLabelText(/Email/), "x");
    await act(() => router.navigate("/models/users", { replace: true, state: SKIP_GUARD }));
    expect(router.state.location.pathname).toBe("/models/users");
    expect(screen.queryByRole("dialog", { name: "Leave this page?" })).toBeNull();
  });

  it("the skip flag never applies to back/forward (history keeps location state)", async () => {
    const { router } = setup("/models/users/items/7");
    await screen.findByLabelText(/Email/);
    // A list entry that was reached with SKIP_GUARD (e.g. after a delete)...
    await act(() => router.navigate("/models/users", { state: SKIP_GUARD }));
    await act(() => router.navigate("/models/users/items/7"));
    await userEvent.type(await screen.findByLabelText(/Email/), "x");
    // ...must not let Back discard new edits silently.
    await act(() => router.navigate(-1));
    expect(await screen.findByRole("dialog", { name: "Leave this page?" })).toBeVisible();
    expect(router.state.location.pathname).toBe("/models/users/items/7");
  });

  it("moves focus to the first field the server rejected", async () => {
    const patch = vi
      .fn()
      .mockRejectedValue(
        new ApiError(422, "validation_error", "Invalid input.", [
          { loc: ["email"], msg: "Already taken", type: "value_error" },
        ]),
      );
    setup("/models/users/items/7", { client: { patch } });
    const email = await screen.findByLabelText(/Email/);
    await userEvent.type(email, "x");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByText("Already taken")).toBeVisible();
    expect(email).toHaveFocus();
  });
});

describe("list integration", () => {
  it("links records and offers to add one", async () => {
    setup("/models/users");
    expect(await screen.findByRole("link", { name: "7" })).toHaveAttribute(
      "href",
      "/models/users/items/7",
    );
    expect(screen.getByRole("link", { name: "Add user" })).toHaveAttribute(
      "href",
      "/models/users/new",
    );
  });
});

describe("own account (ADR-0009)", () => {
  // The signed-in admin is user "1" (see setup's /meta).
  const OWN: Row = { ...ROW, pk: "1", data: { ...ROW.data, id: 1 } };
  const accounts = () => model({ account: { protected_fields: ["is_active"] } });

  it("locks the protected fields and hides delete on the admin's own record", async () => {
    const patch = vi.fn().mockResolvedValue(OWN);
    setup("/models/users/items/1", { meta: accounts(), row: OWN, client: { patch } });
    expect(await screen.findByRole("heading", { name: "User 1" })).toBeVisible();
    expect(screen.getByLabelText("Is active")).toBeDisabled();
    expect(screen.getByText(/This is your account/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    const email = screen.getByLabelText(/Email/);
    await userEvent.clear(email);
    await userEvent.type(email, "me@example.com");
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    await waitFor(() => {
      expect(patch).toHaveBeenCalledWith("/models/users/items/1", { email: "me@example.com" });
    });
  });

  it("only explains the hidden delete when no field is protected or editing is off", async () => {
    const cases = [
      model({ account: { protected_fields: [] } }),
      model({
        account: { protected_fields: ["is_active"] },
        permissions: { create: true, edit: false, delete: true },
      }),
    ];
    for (const meta of cases) {
      const { unmount } = setup("/models/users/items/1", { meta, row: OWN });
      expect(
        await screen.findByText("This is your account: you cannot delete it here."),
      ).toBeVisible();
      expect(screen.queryByText(/sign-in status/)).toBeNull();
      expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
      unmount();
    }
  });

  it("shows no hint when the record cannot be edited or deleted anyway", async () => {
    const meta = model({
      account: { protected_fields: ["is_active"] },
      permissions: { create: true, edit: false, delete: false },
    });
    setup("/models/users/items/1", { meta, row: OWN });
    expect(await screen.findByRole("heading", { name: "User 1" })).toBeVisible();
    expect(screen.queryByText(/This is your account/)).toBeNull();
  });

  it("keeps other accounts fully editable", async () => {
    setup("/models/users/items/7", { meta: accounts() });
    expect(await screen.findByRole("heading", { name: "User 7" })).toBeVisible();
    expect(screen.getByLabelText("Is active")).toBeEnabled();
    expect(screen.queryByText(/This is your account/)).toBeNull();
    expect(screen.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  it("does nothing special on models that do not hold accounts", async () => {
    setup("/models/users/items/1", { row: OWN });
    expect(await screen.findByRole("heading", { name: "User 1" })).toBeVisible();
    expect(screen.getByLabelText("Is active")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Delete" })).toBeVisible();
  });

  it("shows the server's refusal when the UI was out of date", async () => {
    const patch = vi
      .fn()
      .mockRejectedValue(
        new ApiError(409, "self_lockout", "You cannot change your own active or admin status."),
      );
    setup("/models/users/items/1", { row: OWN, client: { patch } });
    await userEvent.click(await screen.findByLabelText("Is active"));
    await userEvent.click(screen.getByRole("button", { name: "Save changes" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You cannot change your own active or admin status.",
    );
  });
});
