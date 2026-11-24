import { render, screen } from "@testing-library/react";

import type { FieldMeta, Row } from "@/api/contract.gen";
import { testField } from "@/test/fixtures";

import { CellValue } from "./cells";
import { isNumeric } from "./fields";

function cell(field: FieldMeta, value: unknown, labels: Row["labels"] = {}) {
  const row: Row = { pk: "1", data: { [field.name]: value }, labels };
  return render(<CellValue field={field} row={row} />);
}

describe("CellValue", () => {
  it("marks empty values for screen readers", () => {
    cell(testField({ name: "email" }), null);
    expect(screen.getByText("Empty")).toHaveClass("sr-only");
  });

  it("renders booleans as icons with text", () => {
    cell(testField({ name: "ok", type: "boolean" }), true);
    expect(screen.getByText("Yes")).toBeInTheDocument();
  });

  it("renders enum labels", () => {
    const field = testField({
      name: "status",
      type: "enum",
      choices: [{ value: "IN_PROGRESS", label: "In progress" }],
    });
    cell(field, "IN_PROGRESS");
    expect(screen.getByText("In progress")).toBeInTheDocument();
  });

  it("prefers relation labels and falls back to the key", () => {
    const field = testField({ name: "team_id", type: "foreign_key" });
    cell(field, 3, { team_id: "Core" });
    expect(screen.getByText("Core")).toBeInTheDocument();
    cell(field, 4);
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("ignores inherited keys when looking up relation labels", () => {
    cell(testField({ name: "constructor", type: "foreign_key" }), 7);
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("keeps big integers sent as strings exact", () => {
    cell(testField({ name: "n", type: "integer" }), "9007199254740993");
    expect(screen.getByText("9007199254740993")).toBeInTheDocument();
  });

  it("formats datetimes but keeps the raw value as a title", () => {
    cell(testField({ name: "at", type: "datetime" }), "2026-11-24T10:30:00+00:00");
    const element = screen.getByTitle("2026-11-24T10:30:00+00:00");
    expect(element.tagName).toBe("TIME");
    expect(element).toHaveAttribute("dateTime", "2026-11-24T10:30:00+00:00");
  });

  it("reads offset-less values of timezone-aware columns as UTC (like the form)", () => {
    cell(testField({ name: "at", type: "datetime", timezone: true }), "2026-01-31T00:00:00");
    const element = screen.getByTitle("2026-01-31T00:00:00");
    const expected = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date("2026-01-31T00:00:00Z"));
    expect(element).toHaveTextContent(expected);
  });

  it("shows naive columns as stored wall-clock time", () => {
    cell(testField({ name: "at", type: "datetime", timezone: false }), "2026-01-31T09:30:00");
    const expected = new Intl.DateTimeFormat(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(2026, 0, 31, 9, 30));
    expect(screen.getByTitle("2026-01-31T09:30:00")).toHaveTextContent(expected);
  });

  it("shows an unparsable datetime as text", () => {
    cell(testField({ name: "at", type: "datetime" }), "not a date");
    expect(screen.getByText("not a date")).toBeInTheDocument();
  });

  it("does not shift dates across time zones", () => {
    cell(testField({ name: "d", type: "date" }), "2026-01-01");
    expect(screen.getByText("2026-01-01")).toBeInTheDocument();
  });

  it("renders JSON compactly and truncated", () => {
    const { container } = cell(testField({ name: "j", type: "json" }), { a: "x".repeat(200) });
    const text = container.querySelector("code")?.textContent ?? "";
    expect(text.length).toBeLessThanOrEqual(81);
    expect(text.startsWith('{"a":"xxx')).toBe(true);
  });

  it("renders markup as text", () => {
    cell(testField({ name: "email" }), "<img src=x onerror=alert(1)>");
    expect(screen.getByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });

  it("knows which types are numeric", () => {
    expect(isNumeric(testField({ name: "n", type: "decimal" }))).toBe(true);
    expect(isNumeric(testField({ name: "s" }))).toBe(false);
  });
});
