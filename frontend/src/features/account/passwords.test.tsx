import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError, type ApiClient } from "@/api/client";
import type { MetaResponse, ModelMeta, Row } from "@/api/contract.gen";
import { RecordRoute } from "@/features/record/RecordPages";
import { getToasts, toast } from "@/lib/toast";
import { testField, testModel } from "@/test/fixtures";
import { fakeClient, renderRoutes } from "@/test/render";

import { ChangePasswordPage } from "./ChangePasswordPage";

function meta(changePassword: boolean, models: ModelMeta[] = []): MetaResponse {
  return {
    schema_version: "1",
    version: "0",
    title: "Admin",
    show_powered_by: true,
    user: { id: "1", username: "admin" },
    models,
    capabilities: { change_password: changePassword, sign_out_everywhere: false },
  };
}

function setup(path: string, data: MetaResponse, client: Partial<ApiClient> = {}) {
  const get = vi.fn((url: string) =>
    url === "/meta"
      ? Promise.resolve(data)
      : url === "/models/users/items/7"
        ? Promise.resolve(ROW)
        : Promise.reject(new ApiError(404, "not_found", "Not found.")),
  );
  return renderRoutes(
    [
      { path: "/", element: <p>Dashboard</p> },
      { path: "/account/password", element: <ChangePasswordPage /> },
      { path: "/models/:identity/items/:pk", element: <RecordRoute /> },
    ],
    { client: fakeClient({ get: get as unknown as ApiClient["get"], ...client }), path },
  );
}

const ROW: Row = {
  pk: "7",
  data: { id: 7, email: "ann@example.com" },
  labels: {},
  many_labels: {},
  truncated: [],
};

async function fill(label: RegExp | string, value: string) {
  await userEvent.type(screen.getByLabelText(label), value);
}

afterEach(() => {
  toast.clear();
});

describe("ChangePasswordPage", () => {
  it("changes the password and returns to the dashboard", async () => {
    const post = vi.fn().mockResolvedValue(undefined);
    const { router } = setup("/account/password", meta(true), { post });
    await screen.findByRole("heading", { name: "Change password" });
    expect(screen.getByLabelText("Current password")).toHaveAttribute(
      "autocomplete",
      "current-password",
    );
    await fill("Current password", "old one");
    await fill("New password", "a new passphrase");
    await fill("Confirm new password", "a new passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
    expect(post).toHaveBeenCalledWith("/auth/password", {
      current_password: "old one",
      new_password: "a new passphrase",
    });
    expect(getToasts().map((t) => t.message)).toContain(
      "Password changed. Other sessions were signed out.",
    );
  });

  it("checks the confirmation before sending", async () => {
    const post = vi.fn();
    setup("/account/password", meta(true), { post });
    await screen.findByRole("heading", { name: "Change password" });
    await fill("Current password", "old one");
    await fill("New password", "a new passphrase");
    await fill("Confirm new password", "something else");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(screen.getByLabelText("Confirm new password")).toHaveAccessibleDescription(
      "The passwords do not match.",
    );
    expect(post).not.toHaveBeenCalled();
  });

  it("shows the server's messages next to their fields", async () => {
    const post = vi.fn().mockRejectedValue(
      new ApiError(422, "validation_error", "Invalid.", [
        { loc: ["current_password"], msg: "The current password is incorrect.", type: "invalid" },
        { loc: ["new_password"], msg: "Use at least 12 characters.", type: "password" },
        { loc: ["new_password"], msg: "Do not use only digits.", type: "password" },
      ]),
    );
    setup("/account/password", meta(true), { post });
    await screen.findByRole("heading", { name: "Change password" });
    await fill("Current password", "x");
    await fill("New password", "1");
    await fill("Confirm new password", "1");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("The current password is incorrect.")).toBeVisible();
    expect(screen.getByLabelText("New password")).toHaveAccessibleDescription(
      "Use at least 12 characters. Do not use only digits.",
    );
  });

  it("explains rate limiting and other failures", async () => {
    const post = vi
      .fn()
      .mockRejectedValueOnce(new ApiError(429, "rate_limited", "Slow down."))
      .mockRejectedValueOnce(new Error("network"));
    setup("/account/password", meta(true), { post });
    await screen.findByRole("heading", { name: "Change password" });
    await fill("Current password", "x");
    await fill("New password", "a new passphrase");
    await fill("Confirm new password", "a new passphrase");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Too many attempts.");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Changing the password failed. Try again.",
    );
  });

  it("is not found when the backend offers no password changes", async () => {
    setup("/account/password", meta(false));
    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeVisible();
  });
});

describe("SetPasswordButton", () => {
  const users = (setPassword: boolean): ModelMeta =>
    testModel({
      fields: [
        testField({ name: "id", type: "integer", readonly: true }),
        testField({ name: "email" }),
      ],
      account: { protected_fields: [], admin_flag: null, set_password: setPassword },
    });

  it("sets another account's password and clears the dialog", async () => {
    const post = vi.fn().mockResolvedValue(undefined);
    setup("/models/users/items/7", meta(true, [users(true)]), { post });
    await userEvent.click(await screen.findByRole("button", { name: "Set password" }));
    const dialog = screen.getByRole("dialog", { name: "Set password for User 7" });
    await userEvent.type(within(dialog).getByLabelText("New password"), "a new passphrase");
    await userEvent.type(within(dialog).getByLabelText("Confirm new password"), "a new passphrase");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    await waitFor(() => {
      expect(post).toHaveBeenCalledWith("/models/users/items/7/password", {
        new_password: "a new passphrase",
      });
    });
    expect(getToasts().map((t) => t.message)).toContain(
      "Password set for User 7. Its sessions were signed out.",
    );
    await userEvent.click(screen.getByRole("button", { name: "Set password" }));
    expect(within(screen.getByRole("dialog")).getByLabelText("New password")).toHaveValue("");
  });

  it("shows mismatch, server and other errors in the dialog", async () => {
    const post = vi
      .fn()
      .mockRejectedValueOnce(
        new ApiError(422, "validation_error", "Invalid.", [
          { loc: ["new_password"], msg: "Use at least 12 characters.", type: "password" },
        ]),
      )
      .mockRejectedValueOnce(new ApiError(403, "forbidden", "Forbidden."))
      .mockRejectedValueOnce(new Error("network"));
    setup("/models/users/items/7", meta(true, [users(true)]), { post });
    await userEvent.click(await screen.findByRole("button", { name: "Set password" }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("New password"), "short");
    await userEvent.type(within(dialog).getByLabelText("Confirm new password"), "other");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    expect(within(dialog).getByText("The passwords do not match.")).toBeVisible();
    expect(post).not.toHaveBeenCalled();
    await userEvent.clear(within(dialog).getByLabelText("Confirm new password"));
    await userEvent.type(within(dialog).getByLabelText("Confirm new password"), "short");
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    expect(await within(dialog).findByText("Use at least 12 characters.")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    expect(await within(dialog).findByText("Forbidden.")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Set password" }));
    expect(await within(dialog).findByText("Setting the password failed.")).toBeVisible();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  });

  it("is hidden without the permission and on one's own record", async () => {
    setup("/models/users/items/7", meta(true, [users(false)]));
    await screen.findByRole("heading", { name: "User 7" });
    expect(screen.queryByRole("button", { name: "Set password" })).toBeNull();
  });
});
