import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/api/hooks";
import { getToasts, toast } from "@/lib/toast";

import { appPath, createUnauthorizedHandler, loginPath } from "./session";

describe("appPath", () => {
  it.each([
    ["/admin", "/admin", "/"],
    ["/admin/", "/admin", "/"],
    ["/admin/models/users", "/admin", "/models/users"],
    ["/admin/models/users", "/admin/", "/models/users"],
    ["/administrator", "/admin", "/administrator"],
    ["/models/users", "/", "/models/users"],
  ])("%s under %s -> %s", (pathname, basename, expected) => {
    expect(appPath(pathname, basename)).toBe(expected);
  });
});

describe("loginPath", () => {
  it("encodes the return path", () => {
    expect(loginPath("/models/users", "?page=2")).toBe("/login?next=%2Fmodels%2Fusers%3Fpage%3D2");
  });
});

describe("unauthorized handler", () => {
  afterEach(() => {
    toast.clear();
  });

  function setup(pathname: string, signedIn: boolean, reauthenticating = false) {
    const queryClient = new QueryClient();
    if (signedIn) queryClient.setQueryData(queryKeys.me, { user: { id: "1", username: "a" } });
    const navigate = vi.fn().mockResolvedValue(undefined);
    const handler = createUnauthorizedHandler({
      queryClient,
      basename: "/admin",
      router: () => ({ state: { location: { pathname, search: "?q=x" } }, navigate }),
      reauthenticating: () => reauthenticating,
    });
    return { queryClient, navigate, handler };
  }

  it("sends an expired session back to login without the basename", () => {
    const { queryClient, navigate, handler } = setup("/admin/models/users", true);
    handler();
    expect(navigate).toHaveBeenCalledWith("/login?next=%2Fmodels%2Fusers%3Fq%3Dx", {
      replace: true,
      state: { skipGuard: true },
    });
    expect(queryClient.getQueryData(queryKeys.me)).toBeUndefined();
    expect(getToasts()).toHaveLength(1);
  });

  it("ignores anonymous visitors (RequireAuth redirects them)", () => {
    const { navigate, handler } = setup("/admin/", false);
    handler();
    expect(navigate).not.toHaveBeenCalled();
    expect(getToasts()).toHaveLength(0);
  });

  it("waits while the in-place sign-in dialog is open (failed reads reload after it)", () => {
    const { queryClient, navigate, handler } = setup("/admin/models/users", true, true);
    handler();
    expect(navigate).not.toHaveBeenCalled();
    expect(queryClient.getQueryData(queryKeys.me)).toBeDefined(); // cache kept
    expect(getToasts()).toHaveLength(0);
  });

  it("does not redirect from the login page", () => {
    const { navigate, handler } = setup("/admin/login", true);
    handler();
    expect(navigate).not.toHaveBeenCalled();
  });
});
