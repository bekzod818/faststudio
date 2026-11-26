/** In-app absolute path such as `/admin` or `/proxy/admin` (never `//host`). */
const APP_PATH = /^\/(?!\/)[^\s\\]*$/u;

function isAppPath(value: unknown): value is string {
  return typeof value === "string" && APP_PATH.test(value) && !value.includes("://");
}

/**
 * Validate the server-rendered block. Hand-written (no zod) so the boot path
 * stays small; unknown keys are ignored, as before.
 */
function parseBlock(raw: unknown): AppConfig | null {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return null;
  const block = raw as Record<string, unknown>;
  const { schema_version: version, base_url: baseUrl, api_url: apiUrl, title } = block;
  const offset = block.max_list_offset;
  if (
    version !== "1" ||
    !isAppPath(baseUrl) ||
    !isAppPath(apiUrl) ||
    typeof title !== "string" ||
    title.length === 0 ||
    typeof offset !== "number" ||
    !Number.isSafeInteger(offset) ||
    offset <= 0
  ) {
    return null;
  }
  return { schemaVersion: version, baseUrl, apiUrl, title, maxListOffset: offset };
}

export interface AppConfig {
  schemaVersion: "1";
  /** Mount path as the browser sees it, without a trailing slash. */
  baseUrl: string;
  /** JSON API base path, e.g. `/admin/api/v1`. */
  apiUrl: string;
  title: string;
  /** Lists never skip this many rows: see `lastReachablePage`. */
  maxListOffset: number;
}

/** Used by `pnpm dev` (Vite serves index.html without the server-rendered block). */
export const DEV_CONFIG: AppConfig = {
  schemaVersion: "1",
  baseUrl: "/admin",
  apiUrl: "/admin/api/v1",
  title: "FastStudio (dev)",
  maxListOffset: 10_000,
};

/**
 * Read the runtime config the server renders into index.html (ADR-0005).
 *
 * @throws Error when the block exists but is malformed: never guess an API origin.
 */
export function readConfig(doc: Document = document): AppConfig {
  const element = doc.getElementById("fs-config");
  if (element === null) {
    return DEV_CONFIG;
  }
  let raw: unknown;
  try {
    raw = JSON.parse(element.textContent);
  } catch {
    throw new Error("FastStudio: the runtime config block is not valid JSON.");
  }
  const config = parseBlock(raw);
  if (config === null) {
    throw new Error("FastStudio: the runtime config block is invalid.");
  }
  return config;
}
