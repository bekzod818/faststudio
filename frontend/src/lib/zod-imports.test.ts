// zod must be told not to JIT (strict CSP) before any schema parses. zod is
// only loaded by lazy chunks, so every module that imports it must import
// "@/lib/zod-setup" first (ES modules evaluate imports in order).
const SOURCES = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

// Static and dynamic imports of zod (any entry point, e.g. "zod/v4", "zod/mini")
// and of the hook-form resolver, in either quote style.
const USES_ZOD =
  /(?:from\s+|import\s*\(\s*)["'](?:zod(?:\/[^"']*)?|@hookform\/resolvers\/zod)["']/u;

it("imports zod-setup before zod in every module that uses zod", () => {
  // `import type` is erased at build time: it does not load zod.
  const runtime = (text: string) =>
    text
      .split("\n")
      .filter((line) => !line.startsWith("import type "))
      .join("\n");
  const users = Object.entries(SOURCES).filter(
    ([path, text]) => USES_ZOD.test(runtime(text)) && !path.endsWith("/lib/zod-setup.ts"),
  );
  expect(users.length).toBeGreaterThan(0);
  const offenders = users
    .filter(([, text]) => {
      const first = text.split("\n").find((line) => line.startsWith("import "));
      return first !== 'import "@/lib/zod-setup"; // first: before any zod schema parses';
    })
    .map(([path]) => path);
  expect(offenders).toEqual([]);
});

it("keeps zod out of the boot path", () => {
  for (const path of ["/src/main.tsx", "/src/lib/config.ts", "/src/app/App.tsx"]) {
    expect(SOURCES[path]).toBeDefined();
    expect(SOURCES[path]).not.toMatch(USES_ZOD);
    expect(SOURCES[path]).not.toContain("zod-setup");
  }
});

it.each([
  'import { z } from "zod";',
  "import * as z from 'zod';",
  'import { z } from "zod/v4";',
  'import { z } from "zod/mini";',
  'const z = await import("zod");',
  'import { zodResolver } from "@hookform/resolvers/zod";',
])("recognises %s", (line) => {
  expect(USES_ZOD.test(line)).toBe(true);
});

it.each(['import { thing } from "zodiac";', 'import "./zod-setup";'])("ignores %s", (line) => {
  expect(USES_ZOD.test(line)).toBe(false);
});
