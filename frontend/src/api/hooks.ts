import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";

import type { QueryParams } from "./client";

import type {
  ChoicesResponse,
  JsonValue,
  LinkCountsResponse,
  ListResponse,
  LoginRequest,
  MetaResponse,
  Row,
  UserResponse,
} from "./contract.gen";
import { useApi } from "./context";

export const queryKeys = {
  me: ["me"] as const,
  meta: ["meta"] as const,
  list: (identity: string, params: QueryParams) => ["list", identity, params] as const,
  item: (identity: string, pk: string) => ["item", identity, pk] as const,
  choices: (identity: string, field: string, q: string) => ["choices", identity, field, q] as const,
  choicePages: (identity: string, field: string, q: string) =>
    ["choices", identity, field, q, "pages"] as const,
  links: (identity: string, pk: string) => ["links", identity, pk] as const,
};

/** Options per page of the choices endpoint (docs/api-contract.md, "Choices"). */
export const CHOICES_PAGE_SIZE = 20;

/** Path of one record; the primary key is always URL-encoded. */
export function itemPath(identity: string, pk: string): string {
  return `${itemsPath(identity)}/${encodeURIComponent(pk)}`;
}

/** One record with every visible field. */
export function useItem(identity: string, pk: string) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.item(identity, pk),
    queryFn: ({ signal }) => api.get<Row>(itemPath(identity, pk), { signal }),
  });
}

/**
 * After any write, lists and relation choices of every model may show stale
 * labels (a renamed team appears in the users list), so all are refreshed.
 */
function invalidateAfterWrite(queryClient: ReturnType<typeof useQueryClient>): void {
  void queryClient.invalidateQueries({ queryKey: ["list"] });
  void queryClient.invalidateQueries({ queryKey: ["choices"] });
  void queryClient.invalidateQueries({ queryKey: ["links"] });
}

export function useCreateItem(identity: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, JsonValue>) => api.post<Row>(itemsPath(identity), body),
    onSuccess: (row) => {
      queryClient.setQueryData(queryKeys.item(identity, row.pk), row);
      invalidateAfterWrite(queryClient);
    },
  });
}

export function useUpdateItem(identity: string, pk: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Record<string, JsonValue>) => api.patch<Row>(itemPath(identity, pk), body),
    onSuccess: (row) => {
      queryClient.setQueryData(queryKeys.item(identity, pk), row);
      invalidateAfterWrite(queryClient);
    },
  });
}

/**
 * Deletes a record. The caller leaves the record's page first and then calls
 * `forget()`: removing the cached record while its page is still mounted
 * would make the page refetch it (a 404).
 */
export function useDeleteItem(identity: string, pk: string) {
  const api = useApi();
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => api.delete(itemPath(identity, pk)),
    onSuccess: () => {
      invalidateAfterWrite(queryClient);
    },
  });
  const forget = () => {
    void queryClient.cancelQueries({ queryKey: queryKeys.item(identity, pk) });
    queryClient.removeQueries({ queryKey: queryKeys.item(identity, pk) });
  };
  return { ...mutation, forget };
}

/** Options for a foreign-key field (first page, 20 items, searchable). */
export function useChoices(identity: string, field: string, q: string, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.choices(identity, field, q),
    queryFn: ({ signal }) =>
      api.get<ChoicesResponse>(choicesPath(identity, field), {
        params: { q: q === "" ? undefined : q },
        signal,
      }),
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

function choicesPath(identity: string, field: string): string {
  return `/models/${encodeURIComponent(identity)}/fields/${encodeURIComponent(field)}/choices`;
}

/**
 * Options for a many-to-many field, page after page (`fetchNextPage`).
 * Stops at the last page the server serves (`lastPage`, the offset cap).
 */
export function useChoicePages(
  identity: string,
  field: string,
  q: string,
  enabled: boolean,
  lastPage: number,
) {
  const api = useApi();
  return useInfiniteQuery({
    queryKey: queryKeys.choicePages(identity, field, q),
    queryFn: ({ pageParam, signal }) =>
      api.get<ChoicesResponse>(choicesPath(identity, field), {
        params: { q: q === "" ? undefined : q, page: pageParam === 1 ? undefined : pageParam },
        signal,
      }),
    initialPageParam: 1,
    getNextPageParam: (last, pages, page) =>
      pages.length * CHOICES_PAGE_SIZE < last.total && page < lastPage ? page + 1 : undefined,
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  });
}

/** Many-to-many links a delete of the record would remove, per field. */
export function useLinkCounts(identity: string, pk: string, enabled: boolean) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.links(identity, pk),
    queryFn: ({ signal }) =>
      api.get<LinkCountsResponse>(`${itemPath(identity, pk)}/links`, { signal }),
    enabled,
    staleTime: 0,
  });
}

/** Path of a model's collection; the identity is always URL-encoded. */
export function itemsPath(identity: string): string {
  return `/models/${encodeURIComponent(identity)}/items`;
}

/** One page of records. The previous page stays visible while the next loads. */
export function useList(identity: string, params: QueryParams) {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.list(identity, params),
    queryFn: ({ signal }) => api.get<ListResponse>(itemsPath(identity), { params, signal }),
    placeholderData: keepPreviousData,
  });
}

/** The signed-in admin; fails with `not_authenticated` when there is no session. */
export function useMe() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: () => api.get<UserResponse>("/auth/me"),
    staleTime: 60_000,
  });
}

/** Registered models and their fields. */
export function useMeta() {
  const api = useApi();
  return useQuery({
    queryKey: queryKeys.meta,
    queryFn: () => api.get<MetaResponse>("/meta"),
    staleTime: 5 * 60_000,
  });
}

export function useLogin() {
  const api = useApi();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: LoginRequest) => api.post<UserResponse>("/auth/login", body),
    onSuccess: (data) => {
      // Queries only: clearing the MutationCache would drop this mutation's own state.
      queryClient.removeQueries();
      queryClient.setQueryData(queryKeys.me, data);
    },
  });
}

/**
 * Ends the session. The caller navigates away first and then drops cached
 * data with {@link useForgetSession}; clearing while the layout is still
 * mounted would make its queries refetch (and 401).
 */
export function useLogout() {
  const api = useApi();
  return useMutation({ mutationFn: () => api.post("/auth/logout") });
}

/** Cancel and drop every cached query (the previous admin's data). */
export function useForgetSession(): () => void {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.cancelQueries();
    queryClient.removeQueries();
  };
}
