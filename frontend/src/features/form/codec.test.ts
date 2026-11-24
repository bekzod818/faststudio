import type { FieldMeta } from "@/api/contract.gen";
import { testField } from "@/test/fixtures";

import { buildBody, fromFormValue, initialValues, isEditable, toFormValue } from "./codec";

const f = (overrides: Partial<FieldMeta> & Pick<FieldMeta, "name">) => testField(overrides);

describe("isEditable", () => {
  it("allows create-only keys on create but never on edit", () => {
    const key = f({ name: "code", primary_key: true, create_only: true });
    expect(isEditable(key, "create")).toBe(true);
    expect(isEditable(key, "edit")).toBe(false);
  });

  it("never edits readonly fields", () => {
    expect(isEditable(f({ name: "id", readonly: true }), "create")).toBe(false);
  });
});

describe("empty values", () => {
  it("is required when the field is required", () => {
    expect(fromFormValue(f({ name: "t", required: true }), "", "create")).toEqual({
      kind: "error",
      message: "This field is required.",
    });
  });

  it("omits optional fields on create so database defaults apply", () => {
    expect(fromFormValue(f({ name: "t", has_default: true }), "", "create")).toEqual({
      kind: "omit",
    });
  });

  it("clears nullable fields on edit", () => {
    expect(fromFormValue(f({ name: "t", type: "integer", nullable: true }), "", "edit")).toEqual({
      kind: "value",
      value: null,
    });
  });

  it("keeps an empty string for non-nullable text on edit", () => {
    expect(fromFormValue(f({ name: "t" }), "", "edit")).toEqual({ kind: "value", value: "" });
  });

  it("requires a value for non-nullable non-text fields on edit", () => {
    expect(fromFormValue(f({ name: "n", type: "integer" }), " ", "edit").kind).toBe("error");
  });
});

describe("fromFormValue", () => {
  const int = f({ name: "n", type: "integer", min_value: -2147483648, max_value: 2147483647 });

  it.each([
    ["42", 42],
    [" -7 ", -7],
  ])("parses integer %s", (input, value) => {
    expect(fromFormValue(int, input, "create")).toEqual({ kind: "value", value });
  });

  it.each(["1.5", "1e3", "abc", "0x10", "2147483648"])("rejects integer %s", (input) => {
    expect(fromFormValue(int, input, "create").kind).toBe("error");
  });

  it("sends integers beyond 2^53 as exact digit strings", () => {
    const big = f({
      name: "n",
      type: "integer",
      min_value: Number.MIN_SAFE_INTEGER * 1024,
      max_value: Number.MAX_SAFE_INTEGER * 1024,
    });
    expect(fromFormValue(big, "9007199254740993", "create")).toEqual({
      kind: "value",
      value: "9007199254740993",
    });
  });

  it("enforces string length in characters", () => {
    const s = f({ name: "s", max_length: 3 });
    expect(fromFormValue(s, "\u{1F600}\u{1F600}\u{1F600}", "create").kind).toBe("value");
    expect(fromFormValue(s, "abcd", "create")).toEqual({
      kind: "error",
      message: "Use at most 3 characters.",
    });
    expect(fromFormValue(s, "a\u0000", "create").kind).toBe("error");
  });

  it("checks floats in linear time", () => {
    const start = performance.now();
    fromFormValue(f({ name: "x", type: "float" }), `${"1".repeat(30_000)}x`, "create");
    expect(performance.now() - start).toBeLessThan(50);
  });

  it("validates floats", () => {
    const x = f({ name: "x", type: "float" });
    expect(fromFormValue(x, "1.25", "create")).toEqual({ kind: "value", value: 1.25 });
    expect(fromFormValue(x, "Infinity", "create").kind).toBe("error");
    expect(fromFormValue(x, "1,5", "create").kind).toBe("error");
  });

  it("validates decimals against precision and scale and keeps them as strings", () => {
    const d = f({ name: "d", type: "decimal", precision: 5, scale: 2 });
    expect(fromFormValue(d, "123.45", "create")).toEqual({ kind: "value", value: "123.45" });
    expect(fromFormValue(d, "1.234", "create").kind).toBe("error");
    expect(fromFormValue(d, "1234.5", "create").kind).toBe("error");
    // Like pydantic: trailing zeros do not count, ".5" and "+1" are numbers.
    const one = f({ name: "d", type: "decimal", precision: 4, scale: 1 });
    expect(fromFormValue(one, "1.50", "create")).toEqual({ kind: "value", value: "1.50" });
    expect(fromFormValue(one, ".5", "create").kind).toBe("value");
    expect(fromFormValue(one, "+1", "create").kind).toBe("value");
    expect(fromFormValue(one, "999", "create").kind).toBe("value");
    expect(fromFormValue(one, "1000", "create").kind).toBe("error"); // 3 whole digits max
    expect(fromFormValue(one, ".", "create").kind).toBe("error");
    const fraction = f({ name: "d", type: "decimal", precision: 2, scale: 2 });
    expect(fromFormValue(fraction, "0.50", "create").kind).toBe("value");
    expect(fromFormValue(fraction, "1.50", "create").kind).toBe("error");
  });

  it("accepts only declared enum values", () => {
    const e = f({ name: "e", type: "enum", choices: [{ value: "A", label: "A" }] });
    expect(fromFormValue(e, "A", "create")).toEqual({ kind: "value", value: "A" });
    expect(fromFormValue(e, "B", "create").kind).toBe("error");
  });

  it("parses booleans, with a tri-state for nullable ones", () => {
    expect(fromFormValue(f({ name: "b", type: "boolean" }), true, "edit")).toEqual({
      kind: "value",
      value: true,
    });
    const nb = f({ name: "b", type: "boolean", nullable: true });
    expect(fromFormValue(nb, "false", "edit")).toEqual({ kind: "value", value: false });
    expect(fromFormValue(nb, "", "edit")).toEqual({ kind: "value", value: null });
  });

  it("converts local datetimes to UTC for timezone-aware columns", () => {
    const aware = f({ name: "at", type: "datetime", timezone: true });
    const result = fromFormValue(aware, "2026-11-24T10:30", "create");
    expect(result).toEqual({ kind: "value", value: new Date("2026-11-24T10:30").toISOString() });
  });

  it("keeps naive datetimes naive", () => {
    const naive = f({ name: "at", type: "datetime", timezone: false });
    expect(fromFormValue(naive, "2026-11-24T10:30", "create")).toEqual({
      kind: "value",
      value: "2026-11-24T10:30:00",
    });
  });

  it("validates dates, JSON and UUIDs", () => {
    expect(fromFormValue(f({ name: "d", type: "date" }), "2026-02-30x", "create").kind).toBe(
      "error",
    );
    expect(fromFormValue(f({ name: "j", type: "json" }), '{"a": [1]}', "create")).toEqual({
      kind: "value",
      value: { a: [1] },
    });
    expect(fromFormValue(f({ name: "j", type: "json" }), "{oops", "create").kind).toBe("error");
    // JSON numbers the server rejects (and JSON.parse would silently mangle).
    const json = f({ name: "j", type: "json" });
    expect(fromFormValue(json, '{"a": 1e400}', "create")).toEqual({
      kind: "error",
      message: "JSON numbers must be finite.",
    });
    expect(fromFormValue(json, "[9007199254740993]", "create")).toEqual({
      kind: "error",
      message: "JSON integers must be between -9007199254740991 and 9007199254740991.",
    });
    expect(fromFormValue(json, '{"n": 1.5e300, "s": "9007199254740993"}', "create").kind).toBe(
      "value",
    );
    const uuid = f({ name: "u", type: "uuid" });
    expect(fromFormValue(uuid, "3F2504E0-4F89-11D3-9A0C-0305E82C3301", "create")).toEqual({
      kind: "value",
      value: "3f2504e0-4f89-11d3-9a0c-0305e82c3301",
    });
    expect(fromFormValue(uuid, "3f2504e04f8911d39a0c0305e82c3301", "create").kind).toBe("error");
  });

  it("parses foreign keys with the target key type", () => {
    const fk = f({
      name: "team_id",
      type: "foreign_key",
      relation: { target_identity: "teams", target_field: "id", value_type: "integer" },
    });
    expect(fromFormValue(fk, "3", "create")).toEqual({ kind: "value", value: 3 });
    const code = f({
      name: "country",
      type: "foreign_key",
      relation: { target_identity: "countries", target_field: "code", value_type: "string" },
    });
    expect(fromFormValue(code, "KZ", "create")).toEqual({ kind: "value", value: "KZ" });
  });
});

describe("toFormValue / initialValues", () => {
  it("renders wire values for inputs", () => {
    expect(toFormValue(f({ name: "n", type: "integer" }), 5)).toBe("5");
    expect(toFormValue(f({ name: "b", type: "boolean" }), null)).toBe(false);
    expect(toFormValue(f({ name: "b", type: "boolean", nullable: true }), null)).toBe("");
    expect(toFormValue(f({ name: "j", type: "json" }), { a: 1 })).toBe('{\n  "a": 1\n}');
    expect(toFormValue(f({ name: "at", type: "datetime" }), "2026-01-02T03:04:05.123456")).toBe(
      "2026-01-02T03:04:05",
    );
  });

  it("shows timezone-aware datetimes in local time (naive values are UTC)", () => {
    const aware = f({ name: "at", type: "datetime", timezone: true });
    const local = toFormValue(aware, "2026-01-02T03:04:05");
    expect(fromFormValue(aware, local, "edit")).toEqual({
      kind: "value",
      value: "2026-01-02T03:04:05.000Z",
    });
  });

  it("starts create forms from published defaults", () => {
    const fields = [
      f({ name: "active", type: "boolean", default: true, has_default: true }),
      f({ name: "title" }),
    ];
    expect(initialValues(fields, undefined)).toEqual({ active: true, title: "" });
  });
});

describe("buildBody", () => {
  const fields = [
    f({ name: "id", type: "integer", readonly: true }),
    f({ name: "title", required: true }),
    f({ name: "priority", type: "integer", has_default: true }),
  ];

  it("sends editable fields only and collects errors per field", () => {
    expect(buildBody(fields, { id: "9", title: "", priority: "x" }, "create")).toEqual({
      body: {},
      errors: { title: "This field is required.", priority: "Enter a whole number." },
    });
    expect(buildBody(fields, { id: "9", title: "Hi", priority: "" }, "create")).toEqual({
      body: { title: "Hi" },
      errors: {},
    });
  });

  it("sends only changed fields on edit", () => {
    expect(
      buildBody(fields, { id: "9", title: "Hi", priority: "3" }, "edit", new Set(["priority"])),
    ).toEqual({ body: { priority: 3 }, errors: {} });
  });
});
