import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";

import { ApiProvider } from "@/api/provider";
import type { ApiClient } from "@/api/client";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import { DEV_CONFIG } from "@/lib/config";
import { ConfigProvider } from "@/lib/ConfigProvider";

export function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    get: vi.fn().mockRejectedValue(new Error("unexpected GET")),
    post: vi.fn().mockRejectedValue(new Error("unexpected POST")),
    patch: vi.fn().mockRejectedValue(new Error("unexpected PATCH")),
    delete: vi.fn().mockRejectedValue(new Error("unexpected DELETE")),
    ...overrides,
  };
}

export function renderRoutes(
  routes: RouteObject[],
  {
    client,
    path = "/",
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  }: { client: ApiClient; path?: string; queryClient?: QueryClient },
): RenderResult & { router: ReturnType<typeof createMemoryRouter>; queryClient: QueryClient } {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const ui: ReactElement = (
    <ConfigProvider value={DEV_CONFIG}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <ApiProvider client={client}>
            <RouterProvider router={router} />
          </ApiProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </ConfigProvider>
  );
  return { ...render(ui), router, queryClient };
}
