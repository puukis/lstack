import { useEffect, useState } from "react";
import { Loader2, Monitor, Moon, RotateCw, Sun } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { StatusBadge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { Overview } from "@/api/types";
import { fmtTs } from "@/lib/format";
import {
  applyThemeChoice,
  getThemeChoice,
  nextThemeChoice,
  PREFERS_DARK_QUERY,
  storeThemeChoice,
  type ThemeChoice,
} from "@/lib/theme";

const themeLabel: Record<ThemeChoice, string> = {
  light: "Light",
  dark: "Dark",
  system: "System",
};

export function Header({ data, isFetching }: { data?: Overview; isFetching?: boolean }) {
  const qc = useQueryClient();
  const [theme, setTheme] = useState<ThemeChoice>(() => getThemeChoice());

  useEffect(() => {
    if (theme !== "system") return;
    const media = window.matchMedia(PREFERS_DARK_QUERY);
    const handler = () => applyThemeChoice("system");
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, [theme]);

  function handleReload() {
    void qc.invalidateQueries();
  }

  function handleThemeClick() {
    const next = nextThemeChoice(theme);
    setTheme(next);
    storeThemeChoice(next);
  }

  const ThemeIcon = theme === "system" ? Monitor : theme === "dark" ? Moon : Sun;

  return (
    <header className="sticky top-0 z-10 flex shrink-0 items-center justify-between gap-4 border-b border-border bg-card px-4 py-3 sm:px-6 lg:px-8">
      <div className="flex min-w-0 flex-col gap-1">
        {data && (
          <>
            <div className="flex min-w-0 items-center gap-2">
              <span className="truncate text-sm font-semibold text-foreground">{data.project.name}</span>
              <StatusBadge status={data.doctor?.status} />
            </div>
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
              <span className="font-mono">{data.project.git_branch}</span>
              <span aria-hidden="true">/</span>
              <span>{data.runtime.os}</span>
              <span aria-hidden="true">/</span>
              <span className="font-mono">{fmtTs(data.generated_at)}</span>
            </div>
          </>
        )}
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <Button variant="ghost" size="sm" onClick={handleThemeClick} aria-label={`Theme: ${themeLabel[theme]}`}>
          <ThemeIcon size={14} />
          <span className="hidden sm:inline">{themeLabel[theme]}</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          onClick={handleReload}
          disabled={isFetching}
          aria-label="Reload all data"
        >
          {isFetching ? <Loader2 size={14} className="animate-spin" /> : <RotateCw size={14} />}
          <span className="hidden sm:inline">Reload</span>
        </Button>
      </div>
    </header>
  );
}
