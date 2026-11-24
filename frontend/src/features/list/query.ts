// List view state lives in the URL (shareable, survives reload, back button
// works). Everything read from the URL is validated against the model's
// metadata so a hand-edited link never produces a 400 from the server.

import type { QueryParams } from "@/api/client";
import type { ModelMeta } from "@/api/contract.gen";
import { hasForbiddenCharacters } from "@/lib/text";

export const MAX_PAGE = 100_000;
export const MAX_SEARCH_LENGTH = 200;
export const MAX_ORDERING = 5;

export interface ListQuery {
  page: number;
  q: string;
  /** `field` or `-field`; empty means the model's default ordering. */
  ordering: string[];
  /** Field name -> wire value (`true`/`false`, a choice value, or `null`). */
  filters: Record<string, string>;
}

const FILTER_KEY = /^filter\[([^\]]+)\]$/u;

function parsePage(raw: string | null): number {
  if (raw === null || !/^[1-9][0-9]{0,5}$/u.test(raw)) return 1;
  const page = Number(raw);
  return page <= MAX_PAGE ? page : 1;
}

/** Length in Unicode code points, as the server counts it. */
export function searchLength(q: string): number {
  // Each surrogate pair (one astral character) counts once.
  return q.replace(/[\uD800-\uDBFF][\uDC00-\uDFFF]/g, "_").length;
}

function parseSearch(raw: string | null, model: ModelMeta): string {
  if (raw === null || model.search_fields.length === 0) return "";
  const q = raw.trim();
  if (searchLength(q) > MAX_SEARCH_LENGTH || hasForbiddenCharacters(q)) return "";
  return q;
}

function parseOrdering(raw: string | null, model: ModelMeta): string[] {
  if (raw === null) return [];
  const seen = new Set<string>();
  const ordering: string[] = [];
  for (const part of raw.split(",")) {
    const field = part.startsWith("-") ? part.slice(1) : part;
    if (!model.sortable_fields.includes(field) || seen.has(field)) continue;
    seen.add(field);
    ordering.push(part);
    if (ordering.length === MAX_ORDERING) break;
  }
  return ordering;
}

/** Values the server accepts for a filter, as strings. */
export function filterValues(model: ModelMeta, field: string): string[] {
  const filter = model.list_filter.find((f) => f.field === field);
  if (filter === undefined) return [];
  const values =
    filter.kind === "boolean" ? ["true", "false"] : filter.choices.map((choice) => choice.value);
  const nullable = model.fields.find((f) => f.name === field)?.nullable ?? false;
  return nullable ? [...values, "null"] : values;
}

function parseFilters(search: URLSearchParams, model: ModelMeta): Record<string, string> {
  // No prototype: field names such as "constructor" must not hit Object.prototype.
  const filters = Object.create(null) as Record<string, string>;
  for (const [key, value] of search) {
    const field = FILTER_KEY.exec(key)?.[1];
    if (field === undefined) continue;
    if (filterValues(model, field).includes(value)) filters[field] = value;
  }
  return filters;
}

export function parseListQuery(search: URLSearchParams, model: ModelMeta): ListQuery {
  return {
    page: parsePage(search.get("page")),
    q: parseSearch(search.get("q"), model),
    ordering: parseOrdering(search.get("ordering"), model),
    filters: parseFilters(search, model),
  };
}

/** URL search params for `query`, leaving out defaults. */
export function toSearchParams(query: ListQuery): URLSearchParams {
  const search = new URLSearchParams();
  if (query.page > 1) search.set("page", String(query.page));
  if (query.q !== "") search.set("q", query.q);
  if (query.ordering.length > 0) search.set("ordering", query.ordering.join(","));
  for (const [field, value] of Object.entries(query.filters)) search.set(`filter[${field}]`, value);
  return search;
}

/** Parameters for `GET /models/{identity}/items`. */
export function toApiParams(query: ListQuery): QueryParams {
  const params: QueryParams = { page: query.page };
  if (query.q !== "") params.q = query.q;
  if (query.ordering.length > 0) params.ordering = query.ordering.join(",");
  for (const [field, value] of Object.entries(query.filters)) params[`filter[${field}]`] = value;
  return params;
}

/** The applied value of a filter, or "" when it is not set. */
export function filterValue(query: ListQuery, field: string): string {
  return Object.hasOwn(query.filters, field) ? (query.filters[field] ?? "") : "";
}

/**
 * Clicking a column header: ascending, then descending, then back to the
 * default. Works from the ordering actually applied, so the first click on
 * the default sort column changes the view, and never produces an explicit
 * copy of the default.
 */
export function nextOrdering(ordering: string[], field: string, defaults: string[]): string[] {
  const current = (ordering.length > 0 ? ordering : defaults)[0];
  let next: string[];
  if (current === field) next = [`-${field}`];
  else if (current === `-${field}`) next = ordering.length === 0 ? [field] : [];
  else next = [field];
  const isDefault =
    next.length === defaults.length && next.every((part, i) => part === defaults[i]);
  return isDefault ? [] : next;
}

/** The ordering actually applied by the server. */
export function effectiveOrdering(ordering: string[], model: ModelMeta): string[] {
  return ordering.length > 0 ? ordering : model.ordering;
}
