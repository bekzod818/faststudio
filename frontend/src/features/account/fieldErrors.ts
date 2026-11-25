export type FieldErrors = Record<string, string>;

/**
 * Server validation details -> one message per field (joined). FastAPI's own
 * body validation prefixes locations with "body"; that part is skipped.
 * Issues for fields the form does not show go to `form`.
 */
export function fieldErrors(
  details: { loc: (string | number)[]; msg: string }[] | null,
  fields: readonly string[],
): FieldErrors {
  const errors: FieldErrors = {};
  for (const issue of details ?? []) {
    const loc = issue.loc[0] === "body" ? issue.loc.slice(1) : issue.loc;
    const name = typeof loc[0] === "string" && fields.includes(loc[0]) ? loc[0] : "form";
    errors[name] = errors[name] === undefined ? issue.msg : `${errors[name]} ${issue.msg}`;
  }
  return errors;
}

/** The first field (in display order) that has an error, if any. */
export function firstInvalid(errors: FieldErrors, order: readonly string[]): string | undefined {
  return order.find((name) => errors[name] !== undefined);
}
