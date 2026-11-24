import { useParams } from "react-router-dom";

import { useMeta } from "@/api/hooks";

import { NotFoundPage } from "./NotFoundPage";

/** Placeholder until the list view (M10) and forms (M11) land. */
export function ModelPage() {
  const { identity } = useParams();
  const meta = useMeta();
  if (meta.isPending) return <p role="status">Loading…</p>;
  if (meta.isError) return <p role="alert">Could not load the admin. Try again later.</p>;
  const model = meta.data.models.find((m) => m.identity === identity);
  if (model === undefined) return <NotFoundPage />;
  return (
    <section>
      <h1 className="text-2xl font-semibold">{model.name_plural}</h1>
      <p className="mt-2 text-muted-foreground">The list view is coming next.</p>
    </section>
  );
}
