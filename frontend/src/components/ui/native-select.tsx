import { forwardRef, type SelectHTMLAttributes } from "react";

import { cn } from "@/lib/utils";

// A styled native <select>: accessible and keyboard-friendly by default, and
// (unlike portal-based selects) it needs no injected styles under our CSP.
export const NativeSelect = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function NativeSelect({ className, ...props }, ref) {
    return (
      <select
        ref={ref}
        className={cn(
          "h-9 rounded-md border border-border bg-background px-2 text-sm",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
          className,
        )}
        {...props}
      />
    );
  },
);
