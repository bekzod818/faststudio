import { screen, waitFor } from "@testing-library/react";

import { ApiError } from "@/api/client";
import { RequireAuth } from "./RequireAuth";
import { fakeClient, renderRoutes } from "@/test/render";

const routes = [
  { path: "/login", element: <p>login page</p> },
  {
    element: <RequireAuth />,
    children: [{ path: "/models/users", element: <p>secret users</p> }],
  },
];

describe("RequireAuth", () => {
  it("redirects to login with the current path as next", async () => {
    const client = fakeClient({
      get: vi
        .fn()
        .mockRejectedValue(new ApiError(401, "not_authenticated", "Authentication required.")),
    });
    const { router } = renderRoutes(routes, { client, path: "/models/users?page=2" });
    await waitFor(() => {
      expect(router.state.location.pathname).toBe("/login");
    });
    expect(router.state.location.search).toBe("?next=%2Fmodels%2Fusers%3Fpage%3D2");
    expect(screen.queryByText("secret users")).not.toBeInTheDocument();
  });

  it("renders the page for a signed-in admin", async () => {
    const client = fakeClient({
      get: vi.fn().mockResolvedValue({ user: { id: "1", username: "admin" } }),
    });
    renderRoutes(routes, { client, path: "/models/users" });
    expect(await screen.findByText("secret users")).toBeInTheDocument();
  });

  it("shows an error instead of redirecting when the server fails", async () => {
    const client = fakeClient({
      get: vi.fn().mockRejectedValue(new ApiError(500, "internal_error", "boom")),
    });
    renderRoutes(routes, { client, path: "/models/users" });
    expect(await screen.findByRole("alert")).toHaveTextContent(/could not load/i);
  });
});
