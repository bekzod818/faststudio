import type { ReactNode } from "react";

import type { AppConfig } from "./config";
import { ConfigContext } from "./config-context";

export function ConfigProvider({ value, children }: { value: AppConfig; children: ReactNode }) {
  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>;
}
