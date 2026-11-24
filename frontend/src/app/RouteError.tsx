import { isRouteErrorResponse, useRouteError } from "react-router-dom";

import { Button } from "@/components/ui/button";

/**
 * Shown when a page fails to render or its code chunk cannot be loaded. The
 * usual cause of the latter is a tab opened before FastStudio was upgraded:
 * its old chunk names no longer exist, and a reload fetches the new ones.
 */
export function RouteError() {
  const error = useRouteError();
  const notFound = isRouteErrorResponse(error) && error.status === 404;
  return (
    <section role="alert" className="flex flex-col items-start gap-3">
      <h1 className="text-2xl font-semibold">
        {notFound ? "Page not found" : "This page could not be loaded"}
      </h1>
      {!notFound && (
        <>
          <p className="text-muted-foreground">
            The admin may have been updated since this tab was opened. Reloading usually fixes this.
          </p>
          <Button
            onClick={() => {
              window.location.reload();
            }}
          >
            Reload
          </Button>
        </>
      )}
    </section>
  );
}

export function PageLoading() {
  return (
    <p role="status" className="p-8 text-muted-foreground">
      Loading…
    </p>
  );
}
