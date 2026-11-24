import * as ToastPrimitive from "@radix-ui/react-toast";
import { CircleAlert, CircleCheck, Info, X } from "lucide-react";
import { useSyncExternalStore } from "react";

import { getToasts, subscribeToasts, toast, type ToastVariant } from "@/lib/toast";
import { cn } from "@/lib/utils";

const ICONS = { info: Info, success: CircleCheck, error: CircleAlert } as const;

const VARIANT_CLASSES: Record<ToastVariant, string> = {
  info: "border-border bg-card text-card-foreground",
  success: "border-border bg-card text-card-foreground",
  error: "border-destructive bg-destructive text-destructive-foreground",
};

/** Renders queued toasts. Mount once, inside the app root. */
export function Toaster({ duration = 5000 }: { duration?: number }) {
  const items = useSyncExternalStore(subscribeToasts, getToasts);
  return (
    <ToastPrimitive.Provider duration={duration} label="Notifications">
      {items.map((item) => {
        const Icon = ICONS[item.variant];
        return (
          <ToastPrimitive.Root
            key={item.id}
            // Errors interrupt screen readers; everything else waits its turn.
            type={item.variant === "error" ? "foreground" : "background"}
            onOpenChange={(open) => {
              if (!open) toast.dismiss(item.id);
            }}
            className={cn(
              "flex items-start gap-3 rounded-md border p-4 shadow-lg",
              VARIANT_CLASSES[item.variant],
            )}
          >
            <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
            <ToastPrimitive.Description className="flex-1 text-sm">
              {item.message}
            </ToastPrimitive.Description>
            <ToastPrimitive.Close
              aria-label="Dismiss notification"
              className="rounded-sm opacity-70 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <X aria-hidden className="size-4" />
            </ToastPrimitive.Close>
          </ToastPrimitive.Root>
        );
      })}
      <ToastPrimitive.Viewport className="fixed bottom-0 right-0 z-50 flex w-full max-w-sm flex-col gap-2 p-4 outline-none" />
    </ToastPrimitive.Provider>
  );
}
