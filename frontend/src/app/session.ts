import type { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "@/api/hooks";
import { toast } from "@/lib/toast";
import { SKIP_GUARD } from "@/lib/unsaved";

/**
 * Strip the router basename (the admin mount, e.g. `/admin`) from a browser
 * pathname. `router.state.location` keeps the basename; `navigate()` expects
 * app paths without it.
 */
export function appPath(pathname: string, basename: string): string {
  const base = basename.replace(/\/+$/u, "");
  if (base === "") return pathname;
  if (pathname === base) return "/";
  if (pathname.startsWith(`${base}/`)) return pathname.slice(base.length);
  return pathname;
}

/** The login route, remembering where to come back to. */
export function loginPath(pathname: string, search = ""): string {
  return `/login?next=${encodeURIComponent(`${pathname}${search}`)}`;
}

interface RouterLike {
  state: { location: { pathname: string; search: string } };
  navigate: (to: string, options: { replace: boolean; state: unknown }) => Promise<void>;
}

/**
 * Called when an API request comes back `401 not_authenticated`. Only a
 * session that ended mid-use is announced; anonymous visitors are sent to the
 * login page by <RequireAuth> without a toast.
 */
export function createUnauthorizedHandler(options: {
  queryClient: QueryClient;
  router: () => RouterLike;
  basename: string;
  /** While the in-place sign-in dialog is open, failed reads wait for it. */
  reauthenticating?: () => boolean;
}): () => void {
  return () => {
    const { queryClient } = options;
    if (queryClient.getQueryData(queryKeys.me) === undefined) return;
    if (options.reauthenticating?.() === true) return;
    void queryClient.cancelQueries();
    queryClient.removeQueries();
    const router = options.router();
    const { pathname, search } = router.state.location;
    const path = appPath(pathname, options.basename);
    if (path === "/login") return;
    toast.info("Your session has ended. Please sign in again.");
    // Never blocked by an unsaved form: the session is gone, saving cannot work.
    void router.navigate(loginPath(path, search), { replace: true, state: SKIP_GUARD });
  };
}
