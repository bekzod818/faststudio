import type { ModelMeta } from "@/api/contract.gen";
import { testModel } from "@/test/fixtures";

import {
  MAX_SEARCH_LENGTH,
  effectiveOrdering,
  filterValue,
  lastReachablePage,
  nextOrdering,
  parseListQuery,
  toApiParams,
  toSearchParams,
} from "./query";

const model: ModelMeta = testModel(); // page_size 2
const CAP = 10_000;

function parse(search: string, cap = CAP) {
  return parseListQuery(new URLSearchParams(search), model, cap);
}

// A page is reachable iff its OFFSET, (page - 1) * pageSize, is < maxListOffset.
// Same vectors as the server (tests/unit/query/test_params.py).
describe("lastReachablePage", () => {
  it.each([
    [10_000, 25, 400],
    [10_000, 30, 334],
    [10_000, 20, 500],
    [10_000, 100, 100],
    [100, 25, 4],
    [1, 25, 1],
    [10_000_000, 1, 10_000_000],
  ])("cap %i, page size %i -> page %i", (cap, pageSize, last) => {
    expect(lastReachablePage(cap, pageSize)).toBe(last);
    expect((last - 1) * pageSize).toBeLessThan(cap);
    expect(last * pageSize).toBeGreaterThanOrEqual(cap);
  });
});

describe("parseListQuery", () => {
  it("defaults to page 1 with nothing applied", () => {
    expect(parse("")).toEqual({ page: 1, q: "", ordering: [], filters: {} });
  });

  it("reads valid values", () => {
    expect(
      parse("page=3&q=%20ann%20&ordering=-email,id&filter[is_active]=false&filter[status]=DONE"),
    ).toEqual({
      page: 3,
      q: "ann",
      ordering: ["-email", "id"],
      filters: { is_active: "false", status: "DONE" },
    });
  });

  it.each(["0", "-1", "1.5", "abc", "1e3", "9999999999", ""])("drops page=%s", (page) => {
    expect(parse(`page=${page}`).page).toBe(1);
  });

  it("clamps a page past the offset cap to the last reachable page", () => {
    // page_size 2, cap 9: offsets 0..8 are reachable, so pages 1..5.
    expect(parse("page=5", 9).page).toBe(5);
    expect(parse("page=6", 9).page).toBe(5);
    expect(parse("page=999999", 9).page).toBe(5);
  });

  it("counts search length in characters, not UTF-16 units", () => {
    const emoji = "\u{1F600}".repeat(MAX_SEARCH_LENGTH);
    expect(parse(`q=${encodeURIComponent(emoji)}`).q).toBe(emoji);
  });

  it("ignores inherited object keys as filter names", () => {
    const tricky = testModel({
      list_filter: [{ field: "constructor", kind: "boolean", choices: [] }],
    });
    const query = parseListQuery(new URLSearchParams(""), tricky, CAP);
    expect(filterValue(query, "constructor")).toBe("");
    expect(
      parseListQuery(new URLSearchParams("filter[toString]=true"), tricky, CAP).filters,
    ).toEqual({});
  });

  it("drops a search that is too long or has control characters", () => {
    expect(parse(`q=${"a".repeat(MAX_SEARCH_LENGTH + 1)}`).q).toBe("");
    expect(parse("q=a%00b").q).toBe("");
    expect(parse("q=a%E2%80%AEb").q).toBe("");
  });

  it("ignores search when the model has no search fields", () => {
    const plain = { ...model, search_fields: [] };
    expect(parseListQuery(new URLSearchParams("q=x"), plain, CAP).q).toBe("");
  });

  it("keeps only sortable, unique fields, at most five", () => {
    expect(parse("ordering=secret,-email,email,,id").ordering).toEqual(["-email", "id"]);
    const many = { ...model, sortable_fields: ["a", "b", "c", "d", "e", "f"] };
    expect(parseListQuery(new URLSearchParams("ordering=a,b,c,d,e,f"), many, CAP).ordering).toEqual(
      ["a", "b", "c", "d", "e"],
    );
  });

  it("keeps only declared filters with allowed values", () => {
    expect(
      parse("filter[is_active]=yes&filter[status]=NOPE&filter[email]=x&filter[__proto__]=1")
        .filters,
    ).toEqual({});
  });

  it("accepts null only for nullable filter fields", () => {
    expect(parse("filter[status]=null").filters).toEqual({ status: "null" });
    expect(parse("filter[is_active]=null").filters).toEqual({});
  });
});

describe("toSearchParams / toApiParams", () => {
  it("round-trips and omits defaults", () => {
    const query = parse("page=2&q=ann&ordering=-email&filter[status]=DONE");
    expect(parseListQuery(toSearchParams(query), model, CAP)).toEqual(query);
    expect(toSearchParams({ page: 1, q: "", ordering: [], filters: {} }).toString()).toBe("");
  });

  it("builds API parameters", () => {
    expect(toApiParams(parse("page=2&q=ann&ordering=-email,id&filter[is_active]=true"))).toEqual({
      page: 2,
      q: "ann",
      ordering: "-email,id",
      "filter[is_active]": "true",
    });
    expect(toApiParams(parse(""))).toEqual({ page: 1 });
  });
});

describe("ordering helpers", () => {
  it("cycles a column: ascending, descending, default", () => {
    expect(nextOrdering([], "email", ["-id"])).toEqual(["email"]);
    expect(nextOrdering(["email"], "email", ["-id"])).toEqual(["-email"]);
    expect(nextOrdering(["-email"], "email", ["-id"])).toEqual([]);
    expect(nextOrdering(["-email"], "id", ["-id"])).toEqual(["id"]);
  });

  it("changes the view on the first click of the default sort column", () => {
    // Default ascending: id -> -id -> default.
    expect(nextOrdering([], "id", ["id"])).toEqual(["-id"]);
    expect(nextOrdering(["-id"], "id", ["id"])).toEqual([]);
    // Default descending: -id -> id -> default (never an explicit copy of it).
    expect(nextOrdering([], "id", ["-id"])).toEqual(["id"]);
    expect(nextOrdering(["id"], "id", ["-id"])).toEqual([]);
  });

  it("falls back to the model ordering", () => {
    expect(effectiveOrdering([], model)).toEqual(["-id"]);
    expect(effectiveOrdering(["email"], model)).toEqual(["email"]);
  });
});
