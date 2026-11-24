import { createContext, useContext } from "react";

import type { ApiClient } from "./client";

export const ApiContext = createContext<ApiClient | null>(null);

/** The API client of the current app. */
export function useApi(): ApiClient {
  const client = useContext(ApiContext);
  if (client === null) throw new Error("useApi must be used inside <ApiProvider>");
  return client;
}
