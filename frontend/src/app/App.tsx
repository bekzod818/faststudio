import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { createBrowserRouter, RouterProvider } from "react-router-dom";

import { createApiClient } from "@/api/client";
import { ApiProvider } from "@/api/provider";
import { RequireAuth } from "@/app/auth/RequireAuth";
import { PageLoading, RouteError } from "@/app/RouteError";
import { Layout } from "@/app/Layout";
import { QUERY_DEFAULTS } from "@/app/query";
import { createReauthenticate, createReauthStore } from "@/app/reauth";
import { ReauthDialog } from "@/app/ReauthDialog";
import { createUnauthorizedHandler } from "@/app/session";
import { ThemeProvider } from "@/app/theme/ThemeProvider";
import { Toaster } from "@/components/ui/toaster";
import { ConfigProvider } from "@/lib/ConfigProvider";
import type { AppConfig } from "@/lib/config";
import { DashboardPage } from "@/pages/DashboardPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

function createRuntime(config: AppConfig) {
  const queryClient = new QueryClient({ defaultOptions: QUERY_DEFAULTS });
  const reauth = createReauthStore();
  const router = createBrowserRouter(
    [
      {
        path: "/login",
        // Lazy, with zod and react-hook-form: signed-in admins rarely need it.
        errorElement: <RouteError />,
        hydrateFallbackElement: <PageLoading />,
        lazy: async () => ({ Component: (await import("@/pages/LoginPage")).LoginPage }),
      },
      {
        element: <RequireAuth />,
        // Shown on first load while a lazily loaded page's chunk arrives.
        hydrateFallbackElement: <PageLoading />,
        children: [
          {
            element: <Layout />,
            children: [
              { index: true, element: <DashboardPage /> },
              // Model pages (table, forms) load on demand: same-origin chunks
              // from assets/, allowed by the CSP.
              {
                path: "models/:identity",
                errorElement: <RouteError />,
                lazy: async () => ({
                  Component: (await import("@/features/list/ListPage")).ModelListRoute,
                }),
              },
              {
                path: "models/:identity/new",
                errorElement: <RouteError />,
                lazy: async () => ({
                  Component: (await import("@/features/record/RecordPages")).CreateRoute,
                }),
              },
              {
                path: "models/:identity/items/:pk",
                errorElement: <RouteError />,
                lazy: async () => ({
                  Component: (await import("@/features/record/RecordPages")).RecordRoute,
                }),
              },
              {
                path: "account/password",
                errorElement: <RouteError />,
                lazy: async () => ({
                  Component: (await import("@/features/account/ChangePasswordPage"))
                    .ChangePasswordPage,
                }),
              },
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
      reauthenticating: reauth.isOpen,
    }),
    reauthenticate: createReauthenticate(queryClient, reauth),
  });
  return { router, queryClient, client, reauth };
}

export function App({ config }: { config: AppConfig }) {
  // useState, not useMemo: React may discard memoized values, and the router
  // and cache must live exactly as long as the app.
  const [{ router, queryClient, client, reauth }] = useState(() => createRuntime(config));
  return (
    <ConfigProvider value={config}>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <ApiProvider client={client}>
            <RouterProvider router={router} />
            <ReauthDialog store={reauth} router={() => router} />
            <Toaster />
          </ApiProvider>
        </QueryClientProvider>
      </ThemeProvider>
    </ConfigProvider>
  );
}
