import { QUERY_DEFAULTS } from "./query";

// Every source file of the app, as text (tests excluded).
const SOURCES = import.meta.glob<string>(["/src/**/*.{ts,tsx}", "!/src/**/*.test.{ts,tsx}"], {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("no background polling (ADR-0013)", () => {
  it("never refetches on its own", () => {
    expect(QUERY_DEFAULTS.queries.refetchOnWindowFocus).toBe(false);
    expect(QUERY_DEFAULTS.queries.refetchInterval).toBe(false);
  });

  it("has no refetchInterval, refetchOnWindowFocus: true or timers that call the API", () => {
    const files = Object.entries(SOURCES);
    expect(files.length).toBeGreaterThan(20);
    const offenders = files
      .filter(([path, text]) => {
        const polling = /refetchInterval\s*:\s*(?!false\b)/u.test(text);
        const focus = /refetchOnWindowFocus\s*:\s*(?!false\b)/u.test(text);
        const timer = /setInterval\s*\(/u.test(text);
        return (polling || focus || timer) && !path.endsWith("/app/query.ts");
      })
      .map(([path]) => path);
    expect(offenders).toEqual([]);
  });

  it("is what the app uses", () => {
    expect(SOURCES["/src/app/App.tsx"]).toContain("defaultOptions: QUERY_DEFAULTS");
  });
});
