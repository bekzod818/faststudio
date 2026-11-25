import { useState, type FormEvent } from "react";

import { ApiError } from "@/api/client";
import { useSetPassword } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { toast } from "@/lib/toast";

import { fieldErrors, type FieldErrors } from "./fieldErrors";
import { PasswordField } from "./PasswordFields";

/** "Set password" for another account (needs every permission; ADR-0013). */
export function SetPasswordButton({
  identity,
  pk,
  title,
}: {
  identity: string;
  pk: string;
  title: string;
}) {
  const [open, setOpen] = useState(false);
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<FieldErrors>({});
  const setPassword = useSetPassword(identity, pk);

  const close = () => {
    // Never keep typed passwords around once the dialog is gone.
    setOpen(false);
    setNext("");
    setConfirm("");
    setErrors({});
  };

  const submit = (event?: FormEvent) => {
    event?.preventDefault();
    if (next !== confirm) {
      setErrors({ confirm: "The passwords do not match." });
      return;
    }
    setErrors({});
    setPassword.mutate(
      { new_password: next },
      {
        onSuccess: () => {
          close();
          toast.success(`Password set for ${title}. Its sessions were signed out.`);
        },
        onError: (error) => {
          if (error instanceof ApiError && error.code === "validation_error") {
            setErrors(fieldErrors(error.details));
          } else {
            setErrors({
              form: error instanceof ApiError ? error.message : "Setting the password failed.",
            });
          }
        },
      },
    );
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        onClick={() => {
          setOpen(true);
        }}
      >
        Set password
      </Button>
      <ConfirmDialog
        open={open}
        title={`Set password for ${title}`}
        description={
          <form noValidate onSubmit={submit} className="flex flex-col gap-3 text-foreground">
            {errors.form !== undefined && (
              <p role="alert" className="text-sm text-destructive">
                {errors.form}
              </p>
            )}
            <PasswordField
              label="New password"
              autoComplete="new-password"
              value={next}
              onChange={setNext}
              error={errors.new_password}
            />
            <PasswordField
              label="Confirm new password"
              autoComplete="new-password"
              value={confirm}
              onChange={setConfirm}
              error={errors.confirm}
            />
          </form>
        }
        confirmLabel={setPassword.isPending ? "Saving…" : "Set password"}
        busy={setPassword.isPending}
        onConfirm={() => {
          submit();
        }}
        onCancel={close}
      />
    </>
  );
}
