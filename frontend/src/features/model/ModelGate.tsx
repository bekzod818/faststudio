import type { ReactNode } from "react";
import { useParams } from "react-router-dom";

import type { ModelMeta } from "@/api/contract.gen";
import { useMeta } from "@/api/hooks";
import { NoAccessPage } from "@/pages/NoAccessPage";

/** Resolves `:identity` from the URL against /meta, then renders `children`. */
export function ModelGate({ children }: { children: (model: ModelMeta) => ReactNode }) {
  const { identity } = useParams();
  const meta = useMeta();
  if (meta.isPending) return <p role="status">Loading…</p>;
  if (meta.isError) return <p role="alert">Could not load the admin. Try again later.</p>;
  const model = meta.data.models.find((m) => m.identity === identity);
  // /meta lists only the models this admin may view (ADR-0011).
  if (model === undefined) return <NoAccessPage />;
  return children(model);
}
