/** "Users" -> "users" inside a sentence, but keep acronyms ("E2E users"). */
export function inSentence(name: string): string {
  return /^[A-Z][a-z]/u.test(name) ? name.charAt(0).toLowerCase() + name.slice(1) : name;
}

/** App routes of a model; identities and keys are always URL-encoded. */
export const routes = {
  list: (identity: string) => `/models/${encodeURIComponent(identity)}`,
  create: (identity: string) => `/models/${encodeURIComponent(identity)}/new`,
  record: (identity: string, pk: string) =>
    `/models/${encodeURIComponent(identity)}/items/${encodeURIComponent(pk)}`,
};
