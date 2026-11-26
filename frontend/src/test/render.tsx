import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderResult } from "@testing-library/react";
import type { ReactElement } from "react";
import { createMemoryRouter, RouterProvider, type RouteObject } from "react-router-dom";

import { ApiProvider } from "@/api/provider";
import type { ApiClient } from "@/api/client";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import { DEV_CONFIG, type AppConfig } from "@/lib/config";
import { ConfigProvider } from "@/lib/ConfigProvider";

export function fakeClient(overrides: Partial<ApiClient> = {}): ApiClient {
  return {
    get: vi.fn().mockRejectedValue(new Error("unexpected GET")),
    post: vi.fn().mockRejectedValue(new Error("unexpected POST")),
    patch: vi.fn().mockRejectedValue(new Error("unexpected PATCH")),
    delete: vi.fn().mockRejectedValue(new Error("unexpected DELETE")),
    abortAll: vi.fn().mockResolvedValue(undefined),
    ...overrides,
  };
}

export function renderRoutes(
  routes: RouteObject[],
  {
    client,
    path = "/",
    queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
    config = DEV_CONFIG,
  }: { client: ApiClient; path?: string; queryClient?: QueryClient; config?: AppConfig },
): RenderResult & { router: ReturnType<typeof createMemoryRouter>; queryClient: QueryClient } {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const ui: ReactElement = (
    <ConfigProvider value={config}>
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
