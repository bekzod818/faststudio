import { tableFeatures, useTable, type ColumnDef } from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, Plus } from "lucide-react";
import { useMemo } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import type { FieldMeta, ModelMeta, Row } from "@/api/contract.gen";
import { useList } from "@/api/hooks";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { NativeSelect } from "@/components/ui/native-select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import { ModelGate } from "@/features/model/ModelGate";
import { inSentence, routes } from "@/features/model/routes";

import { CellValue } from "./cells";
import { EmptyState } from "./EmptyState";
import { isNumeric } from "./fields";
import { Pagination } from "./Pagination";
import {
  effectiveOrdering,
  filterValue,
  filterValues,
  nextOrdering,
  parseListQuery,
  toApiParams,
  toSearchParams,
  type ListQuery,
} from "./query";
import { SearchBox } from "./SearchBox";

// Sorting and pagination happen on the server: the table only needs its core
// row model. Module scope keeps features and the empty fallback stable.
const features = tableFeatures({});
const NO_ROWS: Row[] = [];

/** Route element for `/models/:identity`. */
export function ModelListRoute() {
  // Keyed: switching models resets local state such as the search box.
  return <ModelGate>{(model) => <ListPage key={model.identity} model={model} />}</ModelGate>;
}

export function ListPage({ model }: { model: ModelMeta }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const query = useMemo(() => parseListQuery(searchParams, model), [searchParams, model]);
  const params = useMemo(() => toApiParams(query), [query]);
  const list = useList(model.identity, params);
  const plural = inSentence(model.name_plural);

  const update = (changes: Partial<ListQuery>, options: { replace?: boolean } = {}) => {
    // Any change other than the page itself starts again from page 1.
    const next: ListQuery = { ...query, page: 1, ...changes };
    setSearchParams(toSearchParams(next), { replace: options.replace ?? false });
  };

  const fields = useMemo(() => {
    const byName = new Map(model.fields.map((field) => [field.name, field]));
    return model.list_display
      .map((name) => byName.get(name))
      .filter((field): field is FieldMeta => field !== undefined);
  }, [model]);

  const columns = useMemo<ColumnDef<typeof features, Row>[]>(
    () =>
      fields.map((field, index) => ({
        id: field.name,
        header: field.label,
        // The first column opens the record.
        cell: ({ row }) =>
          index === 0 ? (
            <Link
              to={routes.record(model.identity, row.original.pk)}
              className="font-medium text-primary underline-offset-4 hover:underline"
            >
              <CellValue field={field} row={row.original} />
            </Link>
          ) : (
            <CellValue field={field} row={row.original} />
          ),
      })),
    [fields, model.identity],
  );

  const table = useTable({
    features,
    columns,
    data: list.data?.items ?? NO_ROWS,
    getRowId: (row) => row.pk,
  });

  const fieldByName = useMemo(() => new Map(fields.map((f) => [f.name, f])), [fields]);
  const [sortKey] = effectiveOrdering(query.ordering, model);
  const filtered = query.q !== "" || Object.keys(query.filters).length > 0;

  return (
    <section className="flex flex-col gap-4">
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-3">
          <h1 className="text-2xl font-semibold">{model.name_plural}</h1>
          {list.data !== undefined && (
            <p className="text-sm text-muted-foreground">
              {list.data.total} {list.data.total === 1 ? "record" : "records"}
            </p>
          )}
        </div>
        {model.permissions.create && (
          <Button asChild>
            <Link to={routes.create(model.identity)}>
              <Plus aria-hidden className="size-4" />
              Add {inSentence(model.name)}
            </Link>
          </Button>
        )}
      </header>

      <div className="flex flex-wrap items-end gap-3">
        {model.search_fields.length > 0 && (
          <SearchBox
            label={`Search ${plural}`}
            value={query.q}
            onSearch={(q) => {
              // Starting a search adds a history entry (Back undoes it);
              // refining one replaces it, so typing doesn't flood history.
              update({ q }, { replace: query.q !== "" });
            }}
          />
        )}
        {model.list_filter.map((filter) => {
          const field = model.fields.find((f) => f.name === filter.field);
          const id = `filter-${filter.field}`;
          return (
            <div key={filter.field} className="flex flex-col gap-1">
              <Label htmlFor={id}>{field?.label ?? filter.field}</Label>
              <NativeSelect
                id={id}
                value={filterValue(query, filter.field)}
                onChange={(event) => {
                  const value = event.target.value;
                  const others = Object.entries(query.filters).filter(
                    ([name]) => name !== filter.field,
                  );
                  update({
                    filters: Object.fromEntries(
                      value === "" ? others : [...others, [filter.field, value]],
                    ),
                  });
                }}
              >
                <option value="">All</option>
                {filterValues(model, filter.field).map((value) => (
                  <option key={value} value={value}>
                    {filterLabel(filter.kind, filter.choices, value)}
                  </option>
                ))}
              </NativeSelect>
            </div>
          );
        })}
      </div>

      {list.isPending ? (
        <p role="status" className="text-muted-foreground">
          Loading {plural}…
        </p>
      ) : list.isError && list.data === undefined ? (
        <div role="alert" className="flex flex-col items-start gap-2">
          <p>Could not load {plural}.</p>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={() => void list.refetch()}>
              Try again
            </Button>
            {list.error instanceof ApiError && list.error.code === "invalid_query" && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearchParams({});
                }}
              >
                Reset view
              </Button>
            )}
          </div>
        </div>
      ) : (
        <>
          {list.isError && (
            <div
              role="alert"
              className="flex items-center gap-2 rounded-md border border-destructive px-3 py-2 text-sm"
            >
              <span>Could not refresh {plural}; showing earlier results.</span>
              <Button variant="ghost" size="sm" onClick={() => void list.refetch()}>
                Try again
              </Button>
            </div>
          )}
          <Table
            aria-label={model.name_plural}
            aria-busy={list.isFetching}
            className={cn(list.isPlaceholderData && "opacity-60")}
          >
            <TableHeader>
              {table.getHeaderGroups().map((group) => (
                <TableRow key={group.id}>
                  {group.headers.map((header) => {
                    const field = fieldByName.get(header.column.id);
                    const sortable = model.sortable_fields.includes(header.column.id);
                    const direction =
                      sortKey === header.column.id
                        ? "ascending"
                        : sortKey === `-${header.column.id}`
                          ? "descending"
                          : undefined;
                    const label = <table.FlexRender header={header} />;
                    return (
                      <TableHead
                        key={header.id}
                        aria-sort={sortable ? (direction ?? "none") : undefined}
                        className={cn(field && isNumeric(field) && "text-right")}
                      >
                        {sortable ? (
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 rounded-sm hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            onClick={() => {
                              update({
                                ordering: nextOrdering(
                                  query.ordering,
                                  header.column.id,
                                  model.ordering,
                                ),
                              });
                            }}
                          >
                            {label}
                            <SortIcon direction={direction} />
                          </button>
                        ) : (
                          label
                        )}
                      </TableHead>
                    );
                  })}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getAllCells().map((cell) => {
                    const field = fieldByName.get(cell.column.id);
                    return (
                      <TableCell
                        key={cell.id}
                        className={cn(field && isNumeric(field) && "text-right tabular-nums")}
                      >
                        <table.FlexRender cell={cell} />
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {list.data.items.length === 0 ? (
            <EmptyState
              total={list.data.total}
              filtered={filtered}
              plural={plural}
              onClear={() => {
                setSearchParams({});
              }}
              onFirstPage={() => {
                update({ page: 1 });
              }}
            />
          ) : (
            <Pagination
              page={query.page}
              pageSize={list.data.page_size}
              total={list.data.total}
              shownFrom={(list.data.page - 1) * list.data.page_size + 1}
              shown={list.data.items.length}
              onPage={(page) => {
                update({ page });
              }}
            />
          )}
        </>
      )}
    </section>
  );
}

function filterLabel(
  kind: "boolean" | "choice",
  choices: { value: string; label: string }[],
  value: string,
): string {
  if (value === "null") return "Empty";
  if (kind === "boolean") return value === "true" ? "Yes" : "No";
  return choices.find((choice) => choice.value === value)?.label ?? value;
}

function SortIcon({ direction }: { direction: "ascending" | "descending" | undefined }) {
  if (direction === "ascending") return <ArrowUp aria-hidden className="size-3.5" />;
  if (direction === "descending") return <ArrowDown aria-hidden className="size-3.5" />;
  return <ArrowUpDown aria-hidden className="size-3.5 opacity-40" />;
}
