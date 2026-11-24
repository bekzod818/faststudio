import { Check, X } from "lucide-react";

import type { FieldMeta, Row } from "@/api/contract.gen";
import { Badge } from "@/components/ui/badge";
import { parseWireDateTime } from "@/lib/datetime";

const JSON_PREVIEW = 80;
const dateTimeFormat = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "short",
});

function Empty() {
  return (
    <>
      <span aria-hidden className="text-muted-foreground">
        —
      </span>
      <span className="sr-only">Empty</span>
    </>
  );
}

function asText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function DateTimeValue({ value, aware }: { value: string; aware: boolean }) {
  // Offset-less values of timezone-aware columns are UTC (e.g. from SQLite),
  // as in the form; naive columns show their stored wall-clock time.
  const parsed = parseWireDateTime(value, aware);
  if (Number.isNaN(parsed.getTime())) return <>{value}</>;
  return (
    <time dateTime={value} title={value}>
      {dateTimeFormat.format(parsed)}
    </time>
  );
}

/** One table cell, rendered by field type. Values are always text, never HTML. */
export function CellValue({ field, row }: { field: FieldMeta; row: Row }) {
  const value = row.data[field.name];
  if (value === null || value === undefined) return <Empty />;

  switch (field.type) {
    case "boolean":
      return value === true ? (
        <>
          <Check aria-hidden className="size-4 text-foreground" />
          <span className="sr-only">Yes</span>
        </>
      ) : (
        <>
          <X aria-hidden className="size-4 text-muted-foreground" />
          <span className="sr-only">No</span>
        </>
      );
    case "enum": {
      const text = asText(value);
      const label = field.choices?.find((choice) => choice.value === text)?.label ?? text;
      return <Badge>{label}</Badge>;
    }
    case "foreign_key":
      // Own keys only: a field named "constructor" must not read Object.prototype.
      return (
        <>
          {Object.hasOwn(row.labels, field.name)
            ? (row.labels[field.name] ?? asText(value))
            : asText(value)}
        </>
      );
    case "datetime":
      return typeof value === "string" ? (
        <DateTimeValue value={value} aware={field.timezone === true} />
      ) : (
        <>{asText(value)}</>
      );
    case "json": {
      const text = asText(value);
      return (
        <code className="font-mono text-xs" title={text}>
          {text.length > JSON_PREVIEW ? `${text.slice(0, JSON_PREVIEW)}…` : text}
        </code>
      );
    }
    case "uuid":
      return <span className="font-mono text-xs">{asText(value)}</span>;
    case "text":
    case "string":
    case "unsupported": {
      const text = asText(value);
      return (
        <span className="block max-w-xs truncate" title={text}>
          {text}
        </span>
      );
    }
    default:
      return <>{asText(value)}</>;
  }
}
