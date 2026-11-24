// A tiny toast store. The admin's CSP forbids injected <style> elements, which
// rules out toast libraries that insert their CSS at runtime; the UI lives in
// components/ui/toaster.tsx and is styled with Tailwind classes only.

export type ToastVariant = "info" | "success" | "error";

export interface ToastItem {
  id: number;
  variant: ToastVariant;
  message: string;
}

/** Keep the stack short: older toasts are dropped when a new one arrives. */
export const MAX_TOASTS = 3;

type Listener = () => void;

let items: readonly ToastItem[] = [];
let nextId = 1;
const listeners = new Set<Listener>();

function emit(): void {
  for (const listener of listeners) listener();
}

function push(variant: ToastVariant, message: string): number {
  const id = nextId++;
  items = [...items, { id, variant, message }].slice(-MAX_TOASTS);
  emit();
  return id;
}

export const toast = {
  info: (message: string) => push("info", message),
  success: (message: string) => push("success", message),
  error: (message: string) => push("error", message),
  dismiss(id: number): void {
    const remaining = items.filter((item) => item.id !== id);
    if (remaining.length === items.length) return;
    items = remaining;
    emit();
  },
  /** Test helper: drop every toast. */
  clear(): void {
    items = [];
    emit();
  },
};

export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function getToasts(): readonly ToastItem[] {
  return items;
}
