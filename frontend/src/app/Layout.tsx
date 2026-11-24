import { LogOut } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useNavigate, useNavigation } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useForgetSession, useLogout, useMe, useMeta } from "@/api/hooks";
import { modelIcon } from "@/app/icons";
import { ThemeToggle } from "@/app/theme/ThemeToggle";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { useConfig } from "@/lib/config-context";
import { toast } from "@/lib/toast";
import { SKIP_GUARD, hasUnsavedChanges } from "@/lib/unsaved";
import { cn } from "@/lib/utils";

export function Layout() {
  const config = useConfig();
  const me = useMe();
  const meta = useMeta();
  const logout = useLogout();
  const forgetSession = useForgetSession();
  const navigate = useNavigate();
  const navigation = useNavigation();
  const [confirmSignOut, setConfirmSignOut] = useState(false);

  const leave = async () => {
    try {
      // signedOut: the login page must not bounce us back (cache cleared next).
      // SKIP_GUARD: a confirmed sign-out always reaches the login page.
      await navigate("/login", { replace: true, state: { ...SKIP_GUARD, signedOut: true } });
    } finally {
      forgetSession();
    }
  };

  const signOut = () => {
    if (hasUnsavedChanges() && !confirmSignOut) {
      setConfirmSignOut(true);
      return;
    }
    setConfirmSignOut(false);
    logout.mutate(undefined, {
      onSuccess: () => void leave(),
      onError: (error) => {
        // An already-expired session is handled by the unauthorized handler.
        if (error instanceof ApiError && error.code === "not_authenticated") return;
        toast.error("Sign-out failed. Try again.");
      },
    });
  };

  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b border-border bg-muted/40 md:w-60 md:border-r md:border-b-0">
        <div className="p-4 text-lg font-semibold">
          <NavLink to="/">{config.title}</NavLink>
        </div>
        <nav aria-label="Models" className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col">
          {meta.data?.models.map((model) => {
            const Icon = modelIcon(model.icon);
            return (
              <NavLink
                key={model.identity}
                to={`/models/${encodeURIComponent(model.identity)}`}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-md px-3 py-2 text-sm hover:bg-muted",
                    isActive && "bg-muted font-medium",
                  )
                }
              >
                <Icon aria-hidden className="size-4" />
                {model.name_plural}
              </NavLink>
            );
          })}
        </nav>
      </aside>
      <div className="flex flex-1 flex-col">
        <header className="flex items-center justify-end gap-2 border-b border-border px-4 py-2">
          <span className="text-sm text-muted-foreground">{me.data?.user.username}</span>
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={signOut} disabled={logout.isPending}>
            <LogOut aria-hidden className="size-4" />
            Sign out
          </Button>
        </header>
        {navigation.state === "loading" && (
          <div
            role="progressbar"
            aria-label="Loading page"
            className="h-0.5 w-full animate-pulse bg-primary"
          />
        )}
        <main className="flex-1 p-6" aria-busy={navigation.state === "loading"}>
          <Outlet />
        </main>
        <ConfirmDialog
          open={confirmSignOut}
          title="Sign out?"
          description="You have unsaved changes. They will be lost if you sign out."
          confirmLabel="Sign out"
          cancelLabel="Stay"
          destructive
          onConfirm={signOut}
          onCancel={() => {
            setConfirmSignOut(false);
          }}
        />
        {meta.data?.show_powered_by !== false && (
          <footer className="px-6 py-3 text-xs text-muted-foreground">Powered by FastStudio</footer>
        )}
      </div>
    </div>
  );
}
