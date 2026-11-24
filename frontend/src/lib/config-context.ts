import { createContext, useContext } from "react";

import type { AppConfig } from "./config";

export const ConfigContext = createContext<AppConfig | null>(null);

/** The runtime config rendered into index.html by the server. */
export function useConfig(): AppConfig {
  const config = useContext(ConfigContext);
  if (config === null) throw new Error("useConfig must be used inside <ConfigProvider>");
  return config;
}
