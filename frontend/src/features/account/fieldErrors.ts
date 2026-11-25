export type FieldErrors = Record<string, string>;

/** Server validation details -> one message per field (joined), plus the rest. */
export function fieldErrors(
  details: { loc: (string | number)[]; msg: string }[] | null,
): FieldErrors {
  const errors: FieldErrors = {};
  for (const issue of details ?? []) {
    const name = typeof issue.loc[0] === "string" ? issue.loc[0] : "form";
    errors[name] = errors[name] === undefined ? issue.msg : `${errors[name]} ${issue.msg}`;
  }
  return errors;
}
