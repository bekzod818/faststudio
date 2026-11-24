// Unsaved-changes coordination between forms and app-level navigation.
//
// Forms block in-app navigation while dirty. Some navigations must never be
// blocked: auth redirects (the session is gone; staying would strand a
// signed-out page), sign-out once confirmed, and leaving a deleted record.
// Those pass `SKIP_GUARD` (merged into the location state).

export const SKIP_GUARD = { skipGuard: true } as const;

export function skipsGuard(state: unknown): boolean {
  return (
    typeof state === "object" &&
    state !== null &&
    (state as { skipGuard?: unknown }).skipGuard === true
  );
}

// Ids of forms with unsaved changes (a set, so several forms can coexist).
const dirty = new Set<string>();

/** Called by forms; the app asks before signing out while any is dirty. */
export function setUnsavedChanges(formId: string, value: boolean): void {
  if (value) dirty.add(formId);
  else dirty.delete(formId);
}

export function hasUnsavedChanges(): boolean {
  return dirty.size > 0;
}
