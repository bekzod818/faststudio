import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "@/app/App";
import { readConfig } from "@/lib/config";
import "@/index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("FastStudio: #root element not found");
}

createRoot(root).render(
  <StrictMode>
    <App config={readConfig()} />
  </StrictMode>,
);
