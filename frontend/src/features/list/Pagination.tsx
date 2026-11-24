import type { ReactNode } from "react";
import { ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

import { Button } from "@/components/ui/button";

import { MAX_PAGE } from "./query";

/**
 * `page` is the requested page (from the URL), so quick repeated clicks move
 * on even while the previous page is still displayed; `shownFrom`/`shown`
 * describe the rows currently on screen.
 */
export function Pagination({
  page,
  pageSize,
  total,
  shownFrom,
  shown,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  shownFrom: number;
  shown: number;
  onPage: (page: number) => void;
}) {
  // Pages past MAX_PAGE are not addressable (the server rejects them).
  const pages = Math.min(MAX_PAGE, Math.max(1, Math.ceil(total / pageSize)));
  return (
    <nav
      aria-label="Pagination"
      className="flex flex-wrap items-center justify-between gap-2 text-sm"
    >
      <p className="text-muted-foreground">
        Showing {shownFrom}–{shownFrom + shown - 1} of {total}
      </p>
      <div className="flex items-center gap-1">
        <PageButton
          label="First page"
          disabled={page <= 1}
          onClick={() => {
            onPage(1);
          }}
        >
          <ChevronsLeft aria-hidden className="size-4" />
        </PageButton>
        <PageButton
          label="Previous page"
          disabled={page <= 1}
          onClick={() => {
            onPage(page - 1);
          }}
        >
          <ChevronLeft aria-hidden className="size-4" />
        </PageButton>
        <span className="px-2" aria-live="polite">
          Page {page} of {pages}
        </span>
        <PageButton
          label="Next page"
          disabled={page >= pages}
          onClick={() => {
            onPage(page + 1);
          }}
        >
          <ChevronRight aria-hidden className="size-4" />
        </PageButton>
        <PageButton
          label="Last page"
          disabled={page >= pages}
          onClick={() => {
            onPage(pages);
          }}
        >
          <ChevronsRight aria-hidden className="size-4" />
        </PageButton>
      </div>
    </nav>
  );
}

function PageButton({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string;
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <Button variant="outline" size="icon" aria-label={label} disabled={disabled} onClick={onClick}>
      {children}
    </Button>
  );
}
