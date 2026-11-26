// zod must be told not to JIT (strict CSP) before any schema parses. zod is
// only loaded by lazy chunks, so every module that imports it must import
// "@/lib/zod-setup" first (ES modules evaluate imports in order).
const SOURCES = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const USES_ZOD = /from "(zod|@hookform\/resolvers\/zod)"/u;

it("imports zod-setup before zod in every module that uses zod", () => {
  const users = Object.entries(SOURCES).filter(
    ([path, text]) => USES_ZOD.test(text) && !path.endsWith("/lib/zod-setup.ts"),
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
