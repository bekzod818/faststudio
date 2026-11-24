import { parseWireDateTime } from "./datetime";

describe("parseWireDateTime", () => {
  it("treats offset-less values of timezone-aware columns as UTC", () => {
    expect(parseWireDateTime("2026-01-31T00:00:00", true).toISOString()).toBe(
      "2026-01-31T00:00:00.000Z",
    );
  });

  it("keeps explicit offsets", () => {
    expect(parseWireDateTime("2026-01-31T05:00:00+05:00", true).toISOString()).toBe(
      "2026-01-31T00:00:00.000Z",
    );
  });

  it("reads naive columns as local wall-clock time", () => {
    expect(parseWireDateTime("2026-01-31T09:30:00", false).getHours()).toBe(9);
  });
});
