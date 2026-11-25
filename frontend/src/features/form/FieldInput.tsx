import { forwardRef } from "react";

import type { FieldMeta } from "@/api/contract.gen";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";

import type { FormValue } from "./codec";
import { ManyPicker } from "./ManyPicker";
import { RelationPicker } from "./RelationPicker";

export interface FieldInputProps {
  id: string;
  field: FieldMeta;
  /** The model the form belongs to (relation choices are served per field). */
  identity: string;
  value: FormValue;
  /** Display label of the current foreign-key value, from `Row.labels`. */
  relationLabel: string | undefined;
  /** Labels of the current many-to-many keys, from `Row.many_labels`. */
  manyLabels: Partial<Record<string, string>> | undefined;
  disabled: boolean;
  /** Whether "no value" is a valid choice (nullable, or optional on create). */
  allowEmpty: boolean;
  invalid: boolean;
  describedBy: string | undefined;
  onChange: (value: FormValue) => void;
  onBlur: () => void;
  /** Lets the form move focus to the first invalid field. */
  inputRef: (element: HTMLElement | null) => void;
}

/** The input widget for one field, chosen by its type (docs/api-contract.md). */
export function FieldInput(props: FieldInputProps) {
  const { id, field, value, disabled, invalid, describedBy, onChange, onBlur } = props;
  const common = {
    ref: props.inputRef,
    id,
    disabled,
    onBlur,
    "aria-invalid": invalid,
    "aria-describedby": describedBy,
    // Meaningless for a checkbox (unchecked is a valid answer).
    "aria-required": field.type === "boolean" && !field.nullable ? undefined : field.required,
  };
  const text = typeof value === "string" ? value : "";

  switch (field.type) {
    case "boolean":
      if (typeof value === "boolean") {
        return (
          <input
            {...common}
            type="checkbox"
            className="size-4 accent-primary"
            checked={value}
            onChange={(event) => {
              onChange(event.target.checked);
            }}
          />
        );
      }
      return (
        <NativeSelect
          {...common}
          value={text}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        >
          <option value="">—</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </NativeSelect>
      );
    case "enum":
      return (
        <NativeSelect
          {...common}
          value={text}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        >
          {(props.allowEmpty || text === "") && <option value="">—</option>}
          {(field.choices ?? []).map((choice) => (
            <option key={choice.value} value={choice.value}>
              {choice.label}
            </option>
          ))}
        </NativeSelect>
      );
    case "text":
    case "json":
      return (
        <Textarea
          {...common}
          rows={field.type === "json" ? 6 : 4}
          spellCheck={field.type === "text"}
          className={cn(field.type === "json" && "font-mono text-xs")}
          value={text}
          onChange={(event) => {
            onChange(event.target.value);
          }}
        />
      );
    case "foreign_key":
      if (field.relation?.target_identity != null) {
        return (
          <RelationPicker
            id={id}
            label={field.label}
            identity={props.identity}
            field={field.name}
            value={text}
            initialLabel={props.relationLabel}
            nullable={props.allowEmpty}
            disabled={disabled}
            invalid={invalid}
            describedBy={describedBy}
            inputRef={props.inputRef}
            onChange={onChange}
          />
        );
      }
      return (
        <PlainInput
          {...common}
          value={text}
          onChange={onChange}
          inputMode={field.relation?.value_type === "integer" ? "numeric" : undefined}
        />
      );
    case "integer":
      return <PlainInput {...common} value={text} onChange={onChange} inputMode="numeric" />;
    case "float":
    case "decimal":
      return <PlainInput {...common} value={text} onChange={onChange} inputMode="decimal" />;
    case "date":
      return <PlainInput {...common} value={text} onChange={onChange} type="date" />;
    case "datetime":
      return (
        <PlainInput {...common} value={text} onChange={onChange} type="datetime-local" step={1} />
      );
    case "uuid":
      return (
        <PlainInput
          {...common}
          value={text}
          onChange={onChange}
          className="font-mono"
          spellCheck={false}
        />
      );
    case "many_to_many":
      return (
        <ManyPicker
          id={id}
          label={field.label}
          identity={props.identity}
          field={field.name}
          value={Array.isArray(value) ? value : []}
          initialLabels={props.manyLabels}
          maxItems={field.max_items}
          disabled={disabled}
          invalid={invalid}
          describedBy={describedBy}
          inputRef={props.inputRef}
          onChange={onChange}
          onBlur={onBlur}
        />
      );
    case "unsupported":
      return <PlainInput {...common} value={text} onChange={onChange} readOnly />;
    default:
      return <PlainInput {...common} value={text} onChange={onChange} />;
  }
}

type PlainInputProps = Omit<React.ComponentProps<typeof Input>, "onChange" | "value"> & {
  value: string;
  onChange: (value: string) => void;
};

const PlainInput = forwardRef<HTMLInputElement, PlainInputProps>(function PlainInput(
  { onChange, ...props },
  ref,
) {
  return (
    <Input
      {...props}
      ref={ref}
      onChange={(event) => {
        onChange(event.target.value);
      }}
    />
  );
});
