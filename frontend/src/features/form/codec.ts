// Converts between wire values (the API contract) and form input values.
// Mirrors the server's rules from docs/api-contract.md ("Writes"); the
// server stays authoritative and its 422 details are shown per field.

import type { FieldMeta, JsonValue } from "@/api/contract.gen";
import { searchLength as characterCount } from "@/features/list/query";

export type FormValue = string | boolean;
export type FormValues = Record<string, FormValue>;
export type Mode = "create" | "edit";
export type Parsed =
  { kind: "value"; value: JsonValue } | { kind: "omit" } | { kind: "error"; message: string };

const MAX_TEXT = 65_535;
const INTEGER = /^-?[0-9]{1,19}$/u;
// No overlapping repetitions: linear even on long hostile input.
const FLOAT = /^-?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][-+]?[0-9]+)?$/u;
const DECIMAL = /^[-+]?([0-9]*)(?:\.([0-9]*))?$/u;
const DATE = /^\d{4}-\d{2}-\d{2}$/u;
const LOCAL_DATETIME = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(:\d{2})?$/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/iu;
const OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/u;

const REQUIRED = "This field is required.";

export function isEditable(field: FieldMeta, mode: Mode): boolean {
  if (field.readonly || field.type === "unsupported") return false;
  return mode === "create" || !field.create_only;
}

function ok(value: JsonValue): Parsed {
  return { kind: "value", value };
}

function error(message: string): Parsed {
  return { kind: "error", message };
}

function isValidDate(text: string): boolean {
  if (!DATE.test(text)) return false;
  const date = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().startsWith(text);
}

// min_value/max_value arrive as JSON numbers, so the 64-bit bounds are off by
// one after conversion (2^63 - 1 becomes 2^63). The server is authoritative.
function parseInteger(text: string, field: FieldMeta): Parsed {
  if (!INTEGER.test(text)) return error("Enter a whole number.");
  const big = BigInt(text);
  if (field.min_value !== null && big < BigInt(field.min_value)) {
    return error(`Use a value of at least ${String(field.min_value)}.`);
  }
  if (field.max_value !== null && big > BigInt(field.max_value)) {
    return error(`Use a value of at most ${String(field.max_value)}.`);
  }
  const number = Number(text);
  // Beyond 2^53 JSON numbers lose precision: the server accepts digit strings.
  return ok(Number.isSafeInteger(number) ? number : big.toString());
}

function parseDecimal(text: string, field: FieldMeta): Parsed {
  const match = DECIMAL.exec(text);
  if (match === null || !/[0-9]/u.test(text)) return error("Enter a number such as 12.50.");
  // Count digits like pydantic: no leading zeros ("0.5" has no whole digits)
  // and no trailing zeros after the point ("1.50" has one decimal place).
  const whole = (match[1] ?? "").replace(/^0+/u, "");
  const fraction = (match[2] ?? "").replace(/0+$/u, "");
  if (field.scale !== null && fraction.length > field.scale) {
    return error(`Use at most ${String(field.scale)} decimal places.`);
  }
  if (field.precision !== null) {
    // Same rule as the server: at most precision - scale digits before the point.
    const wholeLimit = field.precision - (field.scale ?? 0);
    if (whole.length > wholeLimit || whole.length + fraction.length > field.precision) {
      return error(`Use at most ${String(wholeLimit)} digits before the decimal point.`);
    }
  }
  return ok(text);
}

function parseDateTime(text: string, field: FieldMeta): Parsed {
  const match = LOCAL_DATETIME.exec(text);
  if (match === null) return error("Enter a date and time.");
  const local = `${match[1] ?? ""}${match[2] ?? ":00"}`;
  if (field.timezone === true) {
    const date = new Date(local); // interpreted in the browser's time zone
    if (Number.isNaN(date.getTime())) return error("Enter a date and time.");
    return ok(date.toISOString());
  }
  return isValidDate(local.slice(0, 10)) ? ok(local) : error("Enter a date and time.");
}

function parseText(text: string, field: FieldMeta): Parsed {
  if (text.includes("\u0000")) return error("Remove the NUL character.");
  const limit = field.max_length ?? MAX_TEXT;
  if (characterCount(text) > limit) return error(`Use at most ${String(limit)} characters.`);
  return ok(text);
}

function parsePresent(field: FieldMeta, raw: string): Parsed {
  const text = field.type === "string" || field.type === "text" ? raw : raw.trim();
  switch (field.type) {
    case "string":
    case "text":
      return parseText(text, field);
    case "integer":
      return parseInteger(text, field);
    case "float": {
      const number = Number(text);
      return FLOAT.test(text) && Number.isFinite(number) ? ok(number) : error("Enter a number.");
    }
    case "decimal":
      return parseDecimal(text, field);
    case "boolean":
      return text === "true" ? ok(true) : text === "false" ? ok(false) : error("Choose yes or no.");
    case "enum":
      return field.choices?.some((choice) => choice.value === text)
        ? ok(text)
        : error("Choose one of the options.");
    case "date":
      return isValidDate(text) ? ok(text) : error("Enter a date.");
    case "datetime":
      return parseDateTime(text, field);
    case "json":
      return parseJson(text);
    case "uuid":
      return UUID.test(text) ? ok(text.toLowerCase()) : error("Enter a UUID (8-4-4-4-12).");
    case "foreign_key":
      return field.relation?.value_type === "integer" ? parseInteger(text, field) : ok(text);
    default:
      return error("This field cannot be edited.");
  }
}

const INTEGER_LITERAL = /^-?[0-9]+$/u;
const MAX_JSON_INTEGER = Number.MAX_SAFE_INTEGER;

/**
 * Parse JSON with the server's rules: finite numbers, integers within
 * ±(2^53 - 1). JSON.parse turns 1e400 into Infinity (sent as null) and
 * rounds big integers, so both would silently change the stored value.
 * Where the browser exposes each number's source text (JSON.parse source
 * access), only integer literals are range-checked, as on the server;
 * elsewhere any integral value beyond 2^53 is refused (stricter).
 */
function parseJson(text: string): Parsed {
  // Mutated inside the reviver: an object, so the type checker sees the writes.
  const found: { problem: string | null } = { problem: null };
  let parsed: unknown;
  try {
    parsed = JSON.parse(text, (_key, value: unknown, context?: { source?: string }) => {
      if (typeof value !== "number" || found.problem !== null) return value;
      if (!Number.isFinite(value)) {
        found.problem = "JSON numbers must be finite.";
      } else if (Number.isInteger(value) && !Number.isSafeInteger(value)) {
        const source = context?.source;
        if (source === undefined || INTEGER_LITERAL.test(source)) {
          found.problem = `JSON integers must be between -${String(MAX_JSON_INTEGER)} and ${String(MAX_JSON_INTEGER)}.`;
        }
      }
      return value;
    });
  } catch {
    return error("Enter valid JSON.");
  }
  return found.problem === null ? ok(parsed) : error(found.problem);
}

/** Form value -> wire value (or an error / "leave it out"). */
export function fromFormValue(field: FieldMeta, value: FormValue, mode: Mode): Parsed {
  if (typeof value === "boolean") return ok(value);
  const isText = field.type === "string" || field.type === "text";
  const empty = isText ? value === "" : value.trim() === "";
  if (!empty) return parsePresent(field, value);
  if (mode === "create") return field.required ? error(REQUIRED) : { kind: "omit" };
  if (field.nullable) return ok(null);
  return isText ? ok("") : error(REQUIRED);
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function localInput(date: Date): string {
  return (
    `${String(date.getFullYear())}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}` +
    `T${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

/** Wire value -> form value. */
export function toFormValue(field: FieldMeta, value: unknown): FormValue {
  if (field.type === "boolean" && !field.nullable) return value === true;
  if (value === null || value === undefined) return "";
  if (field.type === "boolean") return value === true ? "true" : "false";
  if (field.type === "json") return JSON.stringify(value, null, 2);
  if (field.type === "datetime" && typeof value === "string") {
    if (field.timezone === true) {
      // Naive values from timezone-aware columns are UTC (e.g. SQLite).
      const date = new Date(OFFSET.test(value) ? value : `${value}Z`);
      return Number.isNaN(date.getTime()) ? value : localInput(date);
    }
    return value.slice(0, 19);
  }
  return typeof value === "string" ? value : JSON.stringify(value);
}

/** Starting values: the record's values when editing, else published defaults. */
export function initialValues(
  fields: FieldMeta[],
  data: Record<string, unknown> | undefined,
): FormValues {
  const values: FormValues = {};
  for (const field of fields) {
    values[field.name] = toFormValue(field, data === undefined ? field.default : data[field.name]);
  }
  return values;
}

/** Build the request body; on edit only `changed` fields are sent. */
export function buildBody(
  fields: FieldMeta[],
  values: FormValues,
  mode: Mode,
  changed?: ReadonlySet<string>,
): { body: Record<string, JsonValue>; errors: Record<string, string> } {
  const body: Record<string, JsonValue> = {};
  const errors: Record<string, string> = {};
  for (const field of fields) {
    if (!isEditable(field, mode)) continue;
    if (changed !== undefined && !changed.has(field.name)) continue;
    const parsed = fromFormValue(field, values[field.name] ?? "", mode);
    if (parsed.kind === "error") errors[field.name] = parsed.message;
    else if (parsed.kind === "value") body[field.name] = parsed.value;
  }
  return { body, errors };
}
