import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { ApiError } from "@/api/client";
import { LoginPage } from "./LoginPage";
import { fakeClient, renderRoutes } from "@/test/render";

const routes = [
  { path: "/login", element: <LoginPage /> },
  { path: "/", element: <p>home</p> },
  { path: "/models/users", element: <p>users page</p> },
];

describe("LoginPage", () => {
  it("validates before submitting", async () => {
    const post = vi.fn();
    renderRoutes(routes, { client: fakeClient({ post }), path: "/login" });
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Enter your username.")).toBeVisible();
    expect(screen.getByText("Enter your password.")).toBeVisible();
    expect(screen.getByLabelText(/username/i)).toHaveFocus();
    expect(screen.getByLabelText(/username/i)).toHaveAttribute("aria-invalid", "true");
    expect(post).not.toHaveBeenCalled();
  });

  it("signs in and follows a safe next path", async () => {
    const post = vi.fn().mockResolvedValue({ user: { id: "1", username: "admin" } });
    const client = fakeClient({ post });
    const { router } = renderRoutes(routes, { client, path: "/login?next=/models/users" });
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/password/i), "pw-admin");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/models/users");
    });
    expect(post).toHaveBeenCalledWith("/auth/login", {
      username: "admin",
      password: "pw-admin",
    });
  });

  it("ignores an unsafe next path", async () => {
    const client = fakeClient({
      post: vi.fn().mockResolvedValue({ user: { id: "1", username: "admin" } }),
    });
    const { router } = renderRoutes(routes, {
      client,
      path: "/login?next=//evil.example",
    });
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/password/i), "pw");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/");
    });
  });

  it("shows the server's error without revealing which part was wrong", async () => {
    const client = fakeClient({
      post: vi
        .fn()
        .mockRejectedValue(
          new ApiError(401, "invalid_credentials", "Invalid username or password."),
        ),
    });
    renderRoutes(routes, { client, path: "/login" });
    await userEvent.type(screen.getByLabelText(/username/i), "admin");
    await userEvent.type(screen.getByLabelText(/password/i), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /sign in/i }));
    expect(await screen.findByText("Invalid username or password.")).toBeInTheDocument();
    expect(screen.getByLabelText(/password/i)).toHaveValue("");
  });
});
