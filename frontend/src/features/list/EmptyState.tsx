import { Button } from "@/components/ui/button";

export function EmptyState({
  total,
  filtered,
  plural,
  onClear,
  onFirstPage,
}: {
  total: number;
  filtered: boolean;
  plural: string;
  onClear: () => void;
  onFirstPage: () => void;
}) {
  if (total > 0) {
    return (
      <div className="flex flex-col items-start gap-2 text-muted-foreground">
        <p>This page is past the end of the list.</p>
        <Button variant="outline" size="sm" onClick={onFirstPage}>
          Go to the first page
        </Button>
      </div>
    );
  }
  if (filtered) {
    return (
      <div className="flex flex-col items-start gap-2 text-muted-foreground">
        <p>No {plural} match the current search and filters.</p>
        <Button variant="outline" size="sm" onClick={onClear}>
          Clear search and filters
        </Button>
      </div>
    );
  }
  return <p className="text-muted-foreground">No {plural} yet.</p>;
}
