import { Link } from "react-router-dom";

import { useMeta } from "@/api/hooks";
import { modelIcon } from "@/app/icons";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";

export function DashboardPage() {
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Dashboard</h1>
      <DashboardBody />
    </section>
  );
}

function DashboardBody() {
  const meta = useMeta();
  if (meta.isPending) return <p role="status">Loading…</p>;
  if (meta.isError) return <p role="alert">Could not load the models.</p>;
  if (meta.data.models.length === 0) {
    return (
      <p>
        No models are registered yet. Use <code>admin.register(...)</code>.
      </p>
    );
  }
  return (
    <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {meta.data.models.map((model) => {
        const Icon = modelIcon(model.icon);
        return (
          <li key={model.identity}>
            <Link to={`/models/${encodeURIComponent(model.identity)}`} className="block">
              <Card className="transition-colors hover:bg-muted">
                <CardHeader className="flex-row items-center gap-3">
                  <Icon aria-hidden className="size-5" />
                  <CardTitle>{model.name_plural}</CardTitle>
                </CardHeader>
              </Card>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
