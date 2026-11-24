/** Read a cookie by name from `document.cookie` (undefined when absent). */
export function readCookie(name: string, source: string = document.cookie): string | undefined {
  for (const part of source.split(";")) {
    const [key, ...rest] = part.trim().split("=");
    if (key !== name) continue;
    try {
      return decodeURIComponent(rest.join("="));
    } catch {
      return undefined; // malformed (e.g. planted by a sibling app): treat as absent
    }
  }
  return undefined;
}
