import { Navigate, Outlet, useLocation } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useMe } from "@/api/hooks";
import { loginPath } from "@/app/session";
import { SKIP_GUARD } from "@/lib/unsaved";

/** Render child routes for a signed-in admin; otherwise go to login with `next`. */
export function RequireAuth() {
  const location = useLocation();
  const me = useMe();
  if (me.isPending) {
    return (
      <p role="status" className="p-8 text-muted-foreground">
        Loading…
      </p>
    );
  }
  if (me.isError) {
    if (me.error instanceof ApiError && me.error.code === "not_authenticated") {
      return (
        <Navigate to={loginPath(location.pathname, location.search)} replace state={SKIP_GUARD} />
      );
    }
    return (
      <p role="alert" className="p-8 text-destructive">
        Could not load your session. Try again later.
      </p>
    );
  }
  return <Outlet />;
}
