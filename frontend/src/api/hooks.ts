import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import type { QueryParams } from "./client";

import type { ListResponse, LoginRequest, MetaResponse, UserResponse } from "./contract.gen";
import { useApi } from "./context";

export const queryKeys = {
  me: ["me"] as const,
  meta: ["meta"] as const,
  list: (identity: string, params: QueryParams) => ["list", identity, params] as const,
};

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
