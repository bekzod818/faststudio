import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { createApiClient } from "@/api/client";
import { ApiProvider } from "@/api/provider";
import { RequireAuth } from "@/app/auth/RequireAuth";
import { Layout } from "@/app/Layout";
import { shouldRetry } from "@/app/query";
import { createUnauthorizedHandler } from "@/app/session";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import { Toaster } from "@/components/ui/toaster";
import { ConfigProvider } from "@/lib/ConfigProvider";
import type { AppConfig } from "@/lib/config";
import { ModelListRoute } from "@/features/list/ListPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { LoginPage } from "@/pages/LoginPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

function createRuntime(config: AppConfig) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: shouldRetry, refetchOnWindowFocus: false },
      mutations: { retry: false },
    },
  });
  const router = createBrowserRouter(
    [
      { path: "/login", element: <LoginPage /> },
      {
        element: <RequireAuth />,
        children: [
          {
            element: <Layout />,
            children: [
              { index: true, element: <DashboardPage /> },
              { path: "models/:identity", element: <ModelListRoute /> },
              { path: "*", element: <NotFoundPage /> },
            ],
          },
        ],
      },
    ],
    { basename: config.baseUrl },
  );
  const client = createApiClient({
    apiUrl: config.apiUrl,
    onUnauthorized: createUnauthorizedHandler({
      queryClient,
      router: () => router,
      basename: config.baseUrl,
    }),
  });
  return { router, queryClient, client };
}

export function App({ config }: { config: AppConfig }) {
  // useState, not useMemo: React may discard memoized values, and the router
  // and cache must live exactly as long as the app.
  const [{ router, queryClient, client }] = useState(() => createRuntime(config));
  return (
    <ConfigProvider value={config}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <ApiProvider client={client}>
            <RouterProvider router={router} />
            <Toaster />
          </ApiProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </ConfigProvider>
  );
}
