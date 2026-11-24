import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { useController, useForm, type Control } from "react-hook-form";
import { NavigationType, useBlocker } from "react-router-dom";

import { ApiError } from "@/api/client";
import type { FieldMeta, JsonValue, ModelMeta, Row } from "@/api/contract.gen";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Label } from "@/components/ui/label";
import { setUnsavedChanges, skipsGuard } from "@/lib/unsaved";

import { buildBody, initialValues, isEditable, type FormValues, type Mode } from "./codec";
import { FieldInput } from "./FieldInput";

export interface RecordFormProps {
  model: ModelMeta;
  mode: Mode;
  /** The record being edited (edit mode). */
  row?: Row | undefined;
  /** Show every field read-only (editing disabled for this model). */
  readOnly?: boolean;
  submitLabel: string;
  onSubmit: (body: Record<string, JsonValue>) => Promise<Row>;
  onSaved: (row: Row) => void;
  /** Extra buttons next to submit (e.g. delete). */
  actions?: ReactNode;
}

const UNSAVED = "You have unsaved changes.";

/**
 * Schema-driven create/edit form. Validates with the same rules as the
 * server (codec.ts), sends only changed fields on edit, shows server
 * validation errors next to their fields, and guards unsaved changes.
 */
export function RecordForm(props: RecordFormProps) {
  const { model, mode, row, readOnly = false } = props;
  const fields =
    mode === "create" ? model.fields.filter((field) => isEditable(field, "create")) : model.fields;
  const form = useForm<FormValues>({ defaultValues: initialValues(fields, row?.data) });
  const [formError, setFormError] = useState<string | null>(null);
  const alertRef = useRef<HTMLParagraphElement>(null);
  const { isDirty, isSubmitting } = form.formState;

  // Read at navigation time; cleared right before a successful save navigates.
  const guard = useRef(false);
  useLayoutEffect(() => {
    guard.current = isDirty && !readOnly;
  }, [isDirty, readOnly]);
  // The skip flag lives in location state, which history keeps: honour it
  // only for the navigation that set it, never for back/forward ("POP").
  const blocker = useBlocker(
    ({ nextLocation, historyAction }) =>
      guard.current && !(historyAction !== NavigationType.Pop && skipsGuard(nextLocation.state)),
  );
  const formId = useId();
  useEffect(() => {
    setUnsavedChanges(formId, isDirty && !readOnly);
    return () => {
      setUnsavedChanges(formId, false);
    };
  }, [formId, isDirty, readOnly]);
  useEffect(() => {
    if (!isDirty || readOnly) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
    };
  }, [isDirty, readOnly]);

  const save = async (values: FormValues) => {
    setFormError(null);
    const changed = mode === "edit" ? new Set(Object.keys(form.formState.dirtyFields)) : undefined;
    const { body, errors } = buildBody(fields, values, mode, changed);
    const invalid = Object.entries(errors);
    if (invalid.length > 0) {
      for (const [name, message] of invalid) form.setError(name, { type: "client", message });
      setFormError("Please fix the highlighted fields.");
      form.setFocus(invalid[0]?.[0] ?? "");
      return;
    }
    try {
      const saved = await props.onSubmit(body);
      guard.current = false;
      setUnsavedChanges(formId, false);
      form.reset(initialValues(fields, saved.data));
      props.onSaved(saved);
    } catch (error) {
      const placed: string[] = [];
      setFormError(
        applyServerError(error, fields, (name, fieldError) => {
          placed.push(name);
          form.setError(name, fieldError);
        }),
      );
      // Keyboard and screen-reader users land on the problem, as with client errors.
      const first = fields.find((field) => placed.includes(field.name));
      if (first !== undefined) form.setFocus(first.name);
      else requestAnimationFrame(() => alertRef.current?.focus());
    }
  };

  return (
    <form
      noValidate
      onSubmit={(event) => void form.handleSubmit(save)(event)}
      className="flex max-w-2xl flex-col gap-5"
    >
      {formError !== null && (
        <p
          ref={alertRef}
          tabIndex={-1}
          role="alert"
          className="rounded-md border border-destructive px-3 py-2 text-sm text-destructive"
        >
          {formError}
        </p>
      )}
      {fields.map((field) => (
        <FieldRow
          key={field.name}
          field={field}
          control={form.control}
          identity={model.identity}
          mode={mode}
          disabled={readOnly || !isEditable(field, mode)}
          relationLabel={row?.labels[field.name]}
          onEdit={() => {
            form.clearErrors(field.name);
            if (formError !== null) setFormError(null);
          }}
        />
      ))}
      {(!readOnly || props.actions !== undefined) && (
        <div className="flex flex-wrap items-center gap-2 border-t border-border pt-4">
          {!readOnly && (
            <Button type="submit" disabled={isSubmitting || (mode === "edit" && !isDirty)}>
              {isSubmitting ? "Saving…" : props.submitLabel}
            </Button>
          )}
          {props.actions}
        </div>
      )}
      <ConfirmDialog
        open={blocker.state === "blocked"}
        title="Leave this page?"
        description={`${UNSAVED} They will be lost if you leave.`}
        confirmLabel="Discard changes"
        cancelLabel="Stay"
        destructive
        onConfirm={() => {
          blocker.proceed?.();
        }}
        onCancel={() => {
          blocker.reset?.();
        }}
      />
    </form>
  );
}

/** Maps a failed save to field errors; returns the form-level message. */
function applyServerError(
  error: unknown,
  fields: FieldMeta[],
  setError: (name: string, error: { type: string; message: string }) => void,
): string {
  if (!(error instanceof ApiError)) return "Saving failed. Try again.";
  if (error.code === "validation_error" && error.details !== null) {
    const names = new Set(fields.map((field) => field.name));
    const unplaced: string[] = [];
    for (const issue of error.details) {
      const name = issue.loc[0];
      if (typeof name === "string" && names.has(name)) {
        setError(name, { type: "server", message: issue.msg });
      } else {
        unplaced.push(issue.msg);
      }
    }
    return unplaced.length > 0
      ? `Please fix the highlighted fields. ${unplaced.join(" ")}`
      : "Please fix the highlighted fields.";
  }
  return error.message;
}

function FieldRow({
  field,
  control,
  identity,
  mode,
  disabled,
  relationLabel,
  onEdit,
}: {
  field: FieldMeta;
  control: Control<FormValues>;
  identity: string;
  mode: Mode;
  disabled: boolean;
  relationLabel: string | undefined;
  onEdit: () => void;
}) {
  const { field: input, fieldState } = useController({ name: field.name, control });
  const id = `field-${field.name}`;
  const helpId = field.help_text !== null ? `${id}-help` : undefined;
  const errorId = fieldState.error !== undefined ? `${id}-error` : undefined;
  const describedBy = [helpId, errorId].filter(Boolean).join(" ") || undefined;
  const inline = field.type === "boolean" && !field.nullable;

  return (
    <div
      className={inline ? "flex flex-wrap items-center gap-x-3 gap-y-1" : "flex flex-col gap-1.5"}
    >
      <Label htmlFor={id} className={inline ? "order-2" : undefined}>
        {field.label}
        {field.required && !disabled && (
          <span aria-hidden className="ml-0.5 text-destructive">
            *
          </span>
        )}
      </Label>
      <div className={inline ? "order-1" : undefined}>
        <FieldInput
          id={id}
          field={field}
          identity={identity}
          value={input.value}
          relationLabel={relationLabel}
          disabled={disabled}
          allowEmpty={field.nullable || (mode === "create" && !field.required)}
          invalid={fieldState.error !== undefined}
          describedBy={describedBy}
          onChange={(value) => {
            input.onChange(value);
            onEdit();
          }}
          onBlur={input.onBlur}
          inputRef={input.ref}
        />
      </div>
      {field.help_text !== null && (
        <p id={helpId} className="order-3 w-full text-xs text-muted-foreground">
          {field.help_text}
        </p>
      )}
      {fieldState.error !== undefined && (
        <p id={errorId} className="order-4 w-full text-sm text-destructive">
          {fieldState.error.message}
        </p>
      )}
    </div>
  );
}
