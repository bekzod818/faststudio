/**
 * Shown for models missing from /meta and for `403 forbidden` answers. The
 * SPA cannot tell a model that does not exist from one the admin may not
 * view (/meta lists only viewable models), so the page says both.
 */
export function NoAccessPage() {
  return (
    <section>
      <h1 className="text-2xl font-semibold">Not found or no access</h1>
      <p className="mt-2 text-muted-foreground">
        This page does not exist, or you do not have permission to open it. Ask an administrator if
        you need access.
      </p>
    </section>
  );
}
