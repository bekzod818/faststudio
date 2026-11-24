import { useCallback, useEffect, useLayoutEffect, useRef, useState, type FormEvent } from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { hasForbiddenCharacters } from "@/lib/text";

import { MAX_SEARCH_LENGTH, searchLength } from "./query";

export const SEARCH_DELAY_MS = 300;

function problem(text: string): string | null {
  if (hasForbiddenCharacters(text)) return "Search contains invalid characters.";
  if (searchLength(text.trim()) > MAX_SEARCH_LENGTH) {
    return `Search is limited to ${String(MAX_SEARCH_LENGTH)} characters.`;
  }
  return null;
}

/**
 * Debounced search box bound to the URL's `q`. `value` is the applied search;
 * the box follows it when it changes from outside (back/forward, "clear"),
 * but never overwrites what the user kept typing after their own submission.
 */
export function SearchBox({
  label,
  value,
  onSearch,
}: {
  label: string;
  value: string;
  onSearch: (q: string) => void;
}) {
  const [text, setText] = useState(value);
  const [seen, setSeen] = useState(value);
  const [submitted, setSubmitted] = useState(value);
  const error = problem(text);

  if (value !== seen) {
    setSeen(value);
    if (value !== submitted) setText(value);
    // The URL now owns the search again: a later return to an earlier value
    // (e.g. via the back button) must update the box too.
    setSubmitted(value);
  }

  // The parent passes a new callback on every render; keep the latest in a
  // ref so a re-render (e.g. a finished fetch) does not restart the debounce.
  const onSearchRef = useRef(onSearch);
  useLayoutEffect(() => {
    onSearchRef.current = onSearch;
  });
  const search = useCallback((q: string) => {
    setSubmitted(q);
    onSearchRef.current(q);
  }, []);

  useEffect(() => {
    const q = text.trim();
    if (q === value || error !== null) return;
    const timer = setTimeout(() => {
      search(q);
    }, SEARCH_DELAY_MS);
    return () => {
      clearTimeout(timer);
    };
  }, [text, value, error, search]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (error === null && text.trim() !== value) search(text.trim());
  };

  return (
    <form role="search" onSubmit={submit} className="flex min-w-64 flex-1 flex-col gap-1">
      <Label htmlFor="list-search" className="sr-only">
        {label}
      </Label>
      <Input
        id="list-search"
        type="search"
        placeholder={`${label}…`}
        value={text}
        aria-invalid={error !== null}
        aria-describedby={error !== null ? "list-search-error" : undefined}
        onChange={(event) => {
          setText(event.target.value);
        }}
      />
      {error !== null && (
        <p id="list-search-error" role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </form>
  );
}
