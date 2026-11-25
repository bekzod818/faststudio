import { forwardRef, useId } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

/** One password input with its label and error, wired for screen readers. */
export const PasswordField = forwardRef<
  HTMLInputElement,
  {
    label: string;
    value: string;
    onChange: (value: string) => void;
    error: string | undefined;
    autoComplete: "current-password" | "new-password";
    autoFocus?: boolean;
  }
>(function PasswordField({ label, value, onChange, error, autoComplete, autoFocus = false }, ref) {
  const id = useId();
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        ref={ref}
        id={id}
        type="password"
        required
        autoComplete={autoComplete}
        autoFocus={autoFocus}
        value={value}
        aria-invalid={error !== undefined}
        aria-describedby={error !== undefined ? errorId : undefined}
        onChange={(event) => {
          onChange(event.target.value);
        }}
      />
      {error !== undefined && (
        <p id={errorId} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
});
