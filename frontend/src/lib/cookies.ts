/**
 * Read a cookie by name from `document.cookie` (undefined when absent).
 *
 * A name that appears more than once (e.g. planted by a sibling subdomain) is
 * treated as absent, matching the server, which refuses repeated
 * `faststudio_*` cookies.
 */
export function readCookie(name: string, source: string = document.cookie): string | undefined {
  const values: string[] = [];
  for (const part of source.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key === name) values.push(rest.join("="));
  }
  const [raw] = values;
  if (values.length !== 1 || raw === undefined) return undefined;
  try {
    return decodeURIComponent(raw);
  } catch {
    return undefined; // malformed (e.g. planted by a sibling app): treat as absent
  }
}
