import { useEffect, useId, useRef, type ReactNode } from "react";

import { Button } from "@/components/ui/button";

/**
 * A modal confirmation built on the native <dialog> element: focus trapping,
 * Escape and the top layer come from the browser. Unlike portal/scroll-lock
 * dialog libraries it injects no <style> elements, so it works under the
 * admin's strict CSP.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  destructive = false,
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  destructive?: boolean;
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null) return;
    if (open && !dialog.open) {
      dialog.showModal();
      cancelRef.current?.focus(); // the safe choice starts focused
    }
    if (!open && dialog.open) dialog.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      // Escape closes natively: report it as a cancel.
      onCancel={(event) => {
        event.preventDefault();
        if (!busy) onCancel();
      }}
      // The browser may close the dialog anyway (e.g. a repeated Escape):
      // keep the parent's state in sync, or reopen while an action runs.
      onClose={() => {
        if (!open) return;
        if (busy) ref.current?.showModal();
        else onCancel();
      }}
      // m-auto restores the browser's centering (the CSS reset zeroes margins).
      className="m-auto w-full max-w-md rounded-lg border border-border bg-card p-6 text-card-foreground shadow-xl backdrop:bg-black/50"
    >
      <h2 id={titleId} className="text-lg font-semibold">
        {title}
      </h2>
      <div id={descriptionId} className="mt-2 text-sm text-muted-foreground">
        {description}
      </div>
      <div className="mt-6 flex justify-end gap-2">
        <Button ref={cancelRef} variant="outline" onClick={onCancel} disabled={busy}>
          {cancelLabel}
        </Button>
        <Button
          variant={destructive ? "destructive" : "default"}
          onClick={onConfirm}
          disabled={busy}
        >
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
