import { useEffect, useRef, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "@/api/client";
import { useChangePassword, useMeta } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { toast } from "@/lib/toast";
import { NotFoundPage } from "@/pages/NotFoundPage";

import { fieldErrors, firstInvalid, type FieldErrors } from "./fieldErrors";
import { PasswordField } from "./PasswordFields";

const MISMATCH = "The passwords do not match.";
const FIELDS = ["current_password", "new_password", "confirm"] as const;

/** Route element for `/account/password`: change one's own password. */
export function ChangePasswordPage() {
  const meta = useMeta();
  const change = useChangePassword();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const inputs = useRef<Record<string, HTMLInputElement | null>>({});
  const alertRef = useRef<HTMLParagraphElement>(null);

  // Move keyboard and screen-reader users to the first problem.
  useEffect(() => {
    const name = firstInvalid(errors, FIELDS);
    if (name !== undefined) inputs.current[name]?.focus();
    else if (errors.form !== undefined) alertRef.current?.focus();
  }, [errors]);

  if (meta.isPending) return <p role="status">Loading…</p>;
  if (meta.data?.capabilities.change_password !== true) return <NotFoundPage />;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (next !== confirm) {
      setErrors({ confirm: MISMATCH });
      return;
    }
    setErrors({});
    change.mutate(
      { current_password: current, new_password: next },
      {
        onSuccess: () => {
          toast.success("Password changed. Other sessions were signed out.");
          void navigate("/", { replace: true });
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "validation_error") {
            setErrors(fieldErrors(error.details, FIELDS));
          } else if (error instanceof ApiError && error.code === "rate_limited") {
            setErrors({ form: "Too many attempts. Wait a few minutes and try again." });
          } else {
            setErrors({ form: "Changing the password failed. Try again." });
          }
        },
      },
    );
  };

  return (
    <section className="flex max-w-md flex-col gap-4">
      <h1 className="text-2xl font-semibold">Change password</h1>
      <form noValidate onSubmit={submit} className="flex flex-col gap-4">
        {errors.form !== undefined && (
          <p
            role="alert"
            className="rounded-md border border-destructive px-3 py-2 text-sm text-destructive"
          >
            {errors.form}
          </p>
        )}
        <PasswordField
          ref={(element) => {
            inputs.current.current_password = element;
          }}
          label="Current password"
          autoComplete="current-password"
          autoFocus
          value={current}
          onChange={setCurrent}
          error={errors.current_password}
        />
        <PasswordField
          ref={(element) => {
            inputs.current.new_password = element;
          }}
          label="New password"
          autoComplete="new-password"
          value={next}
          onChange={setNext}
          error={errors.new_password}
        />
        <PasswordField
          ref={(element) => {
            inputs.current.confirm = element;
          }}
          label="Confirm new password"
          autoComplete="new-password"
          value={confirm}
          onChange={setConfirm}
          error={errors.confirm}
        />
        <div>
          <Button type="submit" disabled={change.isPending || current === "" || next === ""}>
            {change.isPending ? "Saving…" : "Change password"}
          </Button>
        </div>
      </form>
    </section>
  );
}
