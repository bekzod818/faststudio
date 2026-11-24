import type { FieldMeta } from "@/api/contract.gen";

const NUMERIC = new Set(["integer", "float", "decimal"]);

/** Numeric columns are right-aligned. */
export function isNumeric(field: FieldMeta): boolean {
  return NUMERIC.has(field.type);
}
