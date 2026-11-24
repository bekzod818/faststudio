import type { ModelMeta } from "@/api/contract.gen";
import { testModel } from "@/test/fixtures";

import {
  MAX_PAGE,
  MAX_SEARCH_LENGTH,
  effectiveOrdering,
  filterValue,
  nextOrdering,
  parseListQuery,
  toApiParams,
  toSearchParams,
} from "./query";

const model: ModelMeta = testModel();

function parse(search: string) {
  return parseListQuery(new URLSearchParams(search), model);
}

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

  it.each(["0", "-1", "1.5", "abc", "1e3", String(MAX_PAGE + 1), ""])("drops page=%s", (page) => {
    expect(parse(`page=${page}`).page).toBe(1);
  });

  it("counts search length in characters, not UTF-16 units", () => {
    const emoji = "\u{1F600}".repeat(MAX_SEARCH_LENGTH);
    expect(parse(`q=${encodeURIComponent(emoji)}`).q).toBe(emoji);
  });

  it("ignores inherited object keys as filter names", () => {
    const tricky = testModel({
      list_filter: [{ field: "constructor", kind: "boolean", choices: [] }],
    });
    const query = parseListQuery(new URLSearchParams(""), tricky);
    expect(filterValue(query, "constructor")).toBe("");
    expect(parseListQuery(new URLSearchParams("filter[toString]=true"), tricky).filters).toEqual(
      {},
    );
  });

  it("drops a search that is too long or has control characters", () => {
    expect(parse(`q=${"a".repeat(MAX_SEARCH_LENGTH + 1)}`).q).toBe("");
    expect(parse("q=a%00b").q).toBe("");
    expect(parse("q=a%E2%80%AEb").q).toBe("");
  });

  it("ignores search when the model has no search fields", () => {
    const plain = { ...model, search_fields: [] };
    expect(parseListQuery(new URLSearchParams("q=x"), plain).q).toBe("");
  });

  it("keeps only sortable, unique fields, at most five", () => {
    expect(parse("ordering=secret,-email,email,,id").ordering).toEqual(["-email", "id"]);
    const many = { ...model, sortable_fields: ["a", "b", "c", "d", "e", "f"] };
    expect(parseListQuery(new URLSearchParams("ordering=a,b,c,d,e,f"), many).ordering).toEqual([
      "a",
      "b",
      "c",
      "d",
      "e",
    ]);
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
    expect(parseListQuery(toSearchParams(query), model)).toEqual(query);
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
