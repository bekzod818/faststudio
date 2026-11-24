import { X } from "lucide-react";
import { useEffect, useId, useState, type KeyboardEvent } from "react";

import { useChoices } from "@/api/hooks";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const SEARCH_DELAY_MS = 250;

/**
 * Searchable picker for a foreign key (WAI-ARIA combobox with a listbox).
 * Options come from `/models/{identity}/fields/{field}/choices`; the value is
 * the target's primary key as a string.
 */
export function RelationPicker({
  id,
  label: fieldLabel,
  identity,
  field,
  value,
  initialLabel,
  nullable,
  disabled = false,
  invalid = false,
  describedBy,
  inputRef,
  onChange,
}: {
  id: string;
  /** The field's visible label, used to name the clear button. */
  label: string;
  identity: string;
  field: string;
  value: string;
  initialLabel: string | undefined;
  nullable: boolean;
  disabled?: boolean;
  invalid?: boolean;
  describedBy?: string | undefined;
  inputRef?: (element: HTMLElement | null) => void;
  onChange: (value: string) => void;
}) {
  const listId = useId();
  const [label, setLabel] = useState(initialLabel ?? value);
  const [text, setText] = useState(label);
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const choices = useChoices(identity, field, query, open);
  const items = choices.data?.items ?? [];

  useEffect(() => {
    if (!open) return;
    const typed = text === label ? "" : text.trim();
    const timer = setTimeout(() => {
      setQuery(typed);
    }, SEARCH_DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [text, label, open]);

  const close = () => {
    setOpen(false);
    setActive(-1);
    setText(label);
    setQuery(""); // reopening starts from the full list, not the last search
  };

  const choose = (index: number) => {
    const item = items[index];
    if (item === undefined) return;
    setLabel(item.label);
    setText(item.label);
    setOpen(false);
    setActive(-1);
    onChange(item.value);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!open) setOpen(true);
      setActive((index) => Math.min(index + 1, items.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) setOpen(true);
      setActive((index) => (index < 0 ? items.length - 1 : Math.max(index - 1, 0)));
    } else if ((event.key === "Home" || event.key === "End") && open && items.length > 0) {
      event.preventDefault();
      setActive(event.key === "Home" ? 0 : items.length - 1);
    } else if (event.key === "Enter" && open) {
      event.preventDefault(); // never submit the form while choosing
      choose(active);
    } else if (event.key === "Escape" && open) {
      event.preventDefault();
      close();
    }
  };

  const optionId = (index: number) => `${listId}-option-${String(index)}`;

  return (
    <div className="relative">
      <div className="flex items-center gap-1">
        <Input
          ref={inputRef}
          id={id}
          role="combobox"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && active >= 0 ? optionId(active) : undefined}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          disabled={disabled}
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
        {nullable && value !== "" && !disabled && (
          <button
            type="button"
            aria-label={`Clear ${fieldLabel}`}
            className="rounded-sm p-1 text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            onClick={() => {
              setLabel("");
              setText("");
              onChange("");
            }}
          >
            <X aria-hidden className="size-4" />
          </button>
        )}
      </div>
      <div
        hidden={!open}
        className="absolute z-40 mt-1 w-full rounded-md border border-border bg-card text-sm shadow-lg"
      >
        <ul
          id={listId}
          role="listbox"
          aria-label={fieldLabel}
          className="max-h-64 overflow-auto py-1"
        >
          {items.map((item, index) => (
            <li
              key={item.value}
              id={optionId(index)}
              role="option"
              aria-selected={item.value === value}
              className={cn(
                "cursor-pointer px-3 py-1.5",
                index === active && "bg-muted",
                item.value === value && "font-medium",
              )}
              // mousedown, not click: runs before the input's blur closes the list.
              onMouseDown={(event) => {
                event.preventDefault();
                choose(index);
              }}
            >
              {item.label}
            </li>
          ))}
        </ul>
        {open && (
          <p role="status" className="px-3 py-1.5 text-xs text-muted-foreground empty:hidden">
            {choices.isPending
              ? "Loading…"
              : choices.isError
                ? "Could not load options."
                : items.length === 0
                  ? "No matches."
                  : choices.data.total > items.length
                    ? `Showing ${String(items.length)} of ${String(choices.data.total)}. Type to narrow the list.`
                    : ""}
          </p>
        )}
      </div>
    </div>
  );
}
