import { z } from "zod";

/** In-app absolute path such as `/admin` or `/proxy/admin` (never `//host`). */
const appPath = z
  .string()
  .regex(/^\/(?!\/)[^\s\\]*$/, "must be an absolute path on this site")
  .refine((value) => !value.includes("://"), "must not contain a scheme");

const SpaConfigSchema = z.object({
  schema_version: z.literal("1"),
  base_url: appPath,
  api_url: appPath,
  title: z.string().min(1),
  max_list_offset: z.number().int().positive(),
});

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
  const parsed = SpaConfigSchema.safeParse(raw);
  if (!parsed.success) {
    throw new Error("FastStudio: the runtime config block is invalid.");
  }
  return {
    schemaVersion: parsed.data.schema_version,
    baseUrl: parsed.data.base_url,
    apiUrl: parsed.data.api_url,
    title: parsed.data.title,
    maxListOffset: parsed.data.max_list_offset,
  };
}
