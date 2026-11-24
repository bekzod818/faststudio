/**
 * Code-point ranges the server rejects in usernames: C0/C1 controls, DEL,
 * line/paragraph separators and bidi overrides (log injection).
 */
const FORBIDDEN_RANGES: readonly (readonly [number, number])[] = [
  [0x0000, 0x001f],
  [0x007f, 0x009f],
  [0x2028, 0x2029],
  [0x202a, 0x202e],
  [0x2066, 0x2069],
];

/** True if `value` contains a character the server's username rule forbids. */
export function hasForbiddenCharacters(value: string): boolean {
  for (const char of value) {
    const code = char.codePointAt(0) ?? 0;
    if (FORBIDDEN_RANGES.some(([low, high]) => code >= low && code <= high)) return true;
  }
  return false;
}
