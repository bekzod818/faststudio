import { Monitor, Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";
import { useTheme, type Theme } from "./theme";

/** Cycles light -> dark -> system (follow the OS) -> light. */
const NEXT: Record<Theme, Theme> = { light: "dark", dark: "system", system: "light" };
const ICON = { light: Sun, dark: Moon, system: Monitor } as const;

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const next = NEXT[theme];
  const Icon = ICON[theme];
  return (
    <Button
      variant="ghost"
      size="icon"
      aria-label={`Theme: ${theme}. Switch to ${next}`}
      title={`Theme: ${theme}`}
      onClick={() => {
        setTheme(next);
      }}
    >
      <Icon aria-hidden />
    </Button>
  );
}
