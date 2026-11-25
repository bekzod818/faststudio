import { X } from "lucide-react";
import { useEffect, useId, useState, type KeyboardEvent, type UIEvent } from "react";

import { CHOICES_PAGE_SIZE, useChoicePages } from "@/api/hooks";
import { Input } from "@/components/ui/input";
import { lastReachablePage } from "@/features/list/query";
import { useConfig } from "@/lib/config-context";
import { cn } from "@/lib/utils";

const SEARCH_DELAY_MS = 250;
/** Load the next page when the list is scrolled this close to its end (px). */
const LOAD_MARGIN_PX = 48;

/**
 * Multi-select for a many-to-many field: the chosen items as removable chips,
 * then a searchable WAI-ARIA combobox whose listbox loads further pages of
 * `/models/{identity}/fields/{field}/choices` as it is scrolled or walked
 * with the arrow keys. Choosing an option toggles it; the list stays open.
 * The value is the list of target keys as strings.
 */
export function ManyPicker({
  id,
  label: fieldLabel,
  identity,
  field,
  value,
  initialLabels,
  maxItems,
  disabled = false,
  invalid = false,
  describedBy,
  inputRef,
  onChange,
  onBlur,
}: {
  id: string;
  /** The field's visible label, used to name the chip list and buttons. */
  label: string;
  identity: string;
  field: string;
  value: string[];
  /** Labels of the record's current keys (`Row.many_labels[field]`). */
  initialLabels: Partial<Record<string, string>> | undefined;
  maxItems: number | null;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string | undefined;
  inputRef?: (element: HTMLElement | null) => void;
  onChange: (value: string[]) => void;
  onBlur?: () => void;
}) {
  const listId = useId();
  const chipsId = useId();
  const { maxListOffset } = useConfig();
  const [labels, setLabels] = useState<Partial<Record<string, string>>>(() => ({
    ...initialLabels,
  }));
  const [text, setText] = useState("");
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const pages = useChoicePages(
    identity,
    field,
    query,
    open && !disabled,
    lastReachablePage(maxListOffset, CHOICES_PAGE_SIZE),
  );
  const items = pages.data?.pages.flatMap((page) => page.items) ?? [];
  const total = pages.data?.pages[0]?.total ?? 0;
  const full = maxItems !== null && value.length >= maxItems;
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = pages;

  useEffect(() => {
    if (!open) return;
    const typed = text.trim();
    const timer = setTimeout(() => {
      setQuery(typed);
      setActive(-1);
    }, SEARCH_DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [text, open]);

  const loadMore = () => {
    if (hasNextPage && !isFetchingNextPage) void fetchNextPage();
  };

  const close = () => {
    setOpen(false);
    setActive(-1);
    setText("");
    setQuery(""); // reopening starts from the full list, not the last search
    onBlur?.();
  };

  const remove = (key: string) => {
    onChange(value.filter((item) => item !== key));
  };

  const toggle = (index: number) => {
    const item = items[index];
    if (item === undefined) return;
    if (value.includes(item.value)) {
      remove(item.value);
      return;
    }
    if (full) return;
    setLabels((known) => ({ ...known, [item.value]: item.label }));
    onChange([...value, item.value]);
  };

  const move = (index: number) => {
    setActive(index);
    // Walking onto the last loaded option fetches the next page.
    if (index >= items.length - 1) loadMore();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setOpen(true);
      move(Math.min(active + 1, items.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) setOpen(true);
      move(active < 0 ? items.length - 1 : Math.max(active - 1, 0));
    } else if ((event.key === "Home" || event.key === "End") && open && items.length > 0) {
      event.preventDefault();
      move(event.key === "Home" ? 0 : items.length - 1);
    } else if (event.key === "Enter" && open) {
      event.preventDefault(); // never submit the form while choosing
      // The list may still show the previous search's options: wait for the new ones.
      if (!pages.isPlaceholderData) toggle(active);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
    } else if (event.key === "Backspace" && text === "" && value.length > 0) {
      event.preventDefault();
      remove(value[value.length - 1] ?? "");
    }
  };

  const onScroll = (event: UIEvent<HTMLUListElement>) => {
    const list = event.currentTarget;
    if (list.scrollHeight - list.scrollTop - list.clientHeight < LOAD_MARGIN_PX) loadMore();
  };

  const optionId = (index: number) => `${listId}-option-${String(index)}`;
  // The record may be refetched with keys this picker never saw: use its labels too.
  const labelOf = (key: string) => labels[key] ?? initialLabels?.[key] ?? key;

  const status = pages.isPending
    ? "Loading…"
    : pages.isError
      ? "Could not load options."
      : items.length === 0
        ? "No matches."
        : full
          ? `Limit reached: at most ${String(maxItems)} can be chosen.`
          : isFetchingNextPage
            ? "Loading more…"
            : total > items.length
              ? `Showing ${String(items.length)} of ${String(total)}. Scroll or type to see more.`
              : "";

  return (
    <div className="flex flex-col gap-2">
      <ul
        id={disabled ? id : chipsId}
        aria-label={`Selected ${fieldLabel}`}
        aria-describedby={disabled ? describedBy : undefined}
        className="flex flex-wrap gap-1.5"
      >
        {value.length === 0 && <li className="text-sm text-muted-foreground">None selected.</li>}
        {value.map((key) => (
          <li
            key={key}
            className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2.5 py-0.5 text-sm"
          >
            {labelOf(key)}
            {!disabled && (
              <button
                type="button"
                aria-label={`Remove ${labelOf(key)} from ${fieldLabel}`}
                className="rounded-full p-0.5 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                onClick={() => {
                  remove(key);
                }}
              >
                <X aria-hidden className="size-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {!disabled && (
        <div className="relative">
          <Input
            ref={inputRef}
            id={id}
            role="combobox"
            autoComplete="off"
            placeholder="Search to add…"
            aria-autocomplete="list"
            aria-expanded={open}
            aria-controls={listId}
            aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
            aria-invalid={invalid}
            aria-describedby={[chipsId, describedBy].filter(Boolean).join(" ")}
            value={text}
            onChange={(event) => {
              setText(event.target.value);
              setOpen(true);
              setActive(-1);
            }}
            onFocus={() => {
              setOpen(true);
            }}
            onClick={() => {
              setOpen(true);
            }}
            onBlur={close}
            onKeyDown={onKeyDown}
          />
          <div
            hidden={!open}
            className="absolute z-40 mt-1 w-full rounded-md border border-border bg-card text-sm shadow-lg"
          >
            <ul
              id={listId}
              role="listbox"
              aria-label={fieldLabel}
              aria-multiselectable="true"
              className="max-h-64 overflow-auto py-1"
              onScroll={onScroll}
            >
              {items.map((item, index) => {
                const selected = value.includes(item.value);
                return (
                  <li
                    key={item.value}
                    id={optionId(index)}
                    role="option"
                    aria-selected={selected}
                    aria-disabled={!selected && full}
                    className={cn(
                      "flex cursor-pointer items-center gap-2 px-3 py-1.5",
                      index === active && "bg-muted",
                      selected && "font-medium",
                      !selected && full && "cursor-not-allowed text-muted-foreground",
                    )}
                    // mousedown, not click: runs before the input's blur closes the list.
                    onMouseDown={(event) => {
                      event.preventDefault();
                      setActive(index);
                      toggle(index);
                    }}
                  >
                    <span aria-hidden className="w-4 text-center">
                      {selected ? "✓" : ""}
                    </span>
                    {item.label}
                  </li>
                );
              })}
            </ul>
            {open && (
              <p role="status" className="px-3 py-1.5 text-xs text-muted-foreground empty:hidden">
                {status}
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
