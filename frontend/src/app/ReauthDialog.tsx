import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useId, useRef, useState, useSyncExternalStore, type FormEvent } from "react";

import { ApiError, LOGIN_PATH } from "@/api/client";
import type { UserResponse } from "@/api/contract.gen";
import { useApi } from "@/api/context";
import { queryKeys } from "@/api/hooks";
import type { ReauthStore } from "@/app/reauth";
import { forgetSession } from "@/app/session";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "@/lib/toast";
import { SKIP_GUARD } from "@/lib/unsaved";

interface Navigator {
  navigate: (to: string, options: { replace: boolean; state: unknown }) => Promise<void>;
}

/**
 * The in-place sign-in for a write that met an ended session (see reauth.ts).
 * A native <dialog>, like ConfirmDialog, so it works under the strict CSP.
 */
export function ReauthDialog({ store, router }: { store: ReauthStore; router: () => Navigator }) {
  const open = useSyncExternalStore(store.subscribe, store.isOpen);
  const api = useApi();
  const queryClient = useQueryClient();
  const ref = useRef<HTMLDialogElement>(null);
  const passwordRef = useRef<HTMLInputElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [previous, setPrevious] = useState<UserResponse | undefined>(undefined);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    if (open && !dialog.open) {
      const me = queryClient.getQueryData<UserResponse>(queryKeys.me);
      setPrevious(me);
      setUsername(me?.user.username ?? "");
      dialog.showModal();
      passwordRef.current?.focus();
    }
    if (!open && dialog.open) dialog.close();
  }, [open, queryClient]);

  const finish = (outcome: "retry" | "discard" | "cancel") => {
    // Never keep a typed password once the dialog is gone.
    setPassword("");
    setError(null);
    setBusy(false);
    store.settle(outcome);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (username === "" || password === "") {
      setError("Enter your username and password.");
      return;
    }
    setBusy(true);
    setError(null);
    let data: UserResponse;
    try {
      data = await api.post<UserResponse>(LOGIN_PATH, { username, password });
    } catch (failure) {
      setPassword("");
      setBusy(false);
      setError(failure instanceof ApiError ? failure.message : "Sign-in failed.");
      passwordRef.current?.focus();
      return;
    }
    if (previous !== undefined && data.user.id === previous.user.id) {
      queryClient.setQueryData(queryKeys.me, data);
      // Reads that failed while the session was gone load again.
      void queryClient.invalidateQueries();
      finish("retry");
      return;
    }
    // Another account: nothing of the previous one may be saved or shown.
    forgetSession(queryClient);
    queryClient.setQueryData(queryKeys.me, data);
    finish("discard");
    toast.info(`Signed in as ${data.user.username}. The unsaved changes were discarded.`);
    void router().navigate("/", { replace: true, state: SKIP_GUARD });
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) finish("cancel");
      }}
      onClose={() => {
        if (!store.isOpen()) return;
        if (busy) ref.current?.showModal();
        else finish("cancel");
      }}
      className="m-auto w-full max-w-sm rounded-lg border border-border bg-card p-6 text-card-foreground shadow-xl backdrop:bg-black/50"
    >
      {open && (
        <form className="flex flex-col gap-4" onSubmit={(event) => void submit(event)} noValidate>
          <h2 id={titleId} className="text-lg font-semibold">
            Sign in to continue
          </h2>
          <p id={descriptionId} className="text-sm text-muted-foreground">
            Your session has ended. Sign in again to save your changes; nothing you entered is lost.
          </p>
          {error !== null && (
            <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </p>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="reauth-username">Username</Label>
            <Input
              id="reauth-username"
              autoComplete="username"
              value={username}
              onChange={(event) => {
                setUsername(event.target.value);
              }}
            />
          </div>
          <div className="flex flex-col gap-2">
            <Label htmlFor="reauth-password">Password</Label>
            <Input
              id="reauth-password"
              ref={passwordRef}
              autoFocus
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => {
                setPassword(event.target.value);
              }}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={busy}
              onClick={() => {
                finish("cancel");
              }}
            >
              Discard changes
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Signing in…" : "Sign in and save"}
            </Button>
          </div>
        </form>
      )}
    </dialog>
  );
}
