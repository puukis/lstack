import { Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import type { ActionItem } from "@/api/types";

const dangerColors: Record<string, string> = {
  low: "text-accent-foreground",
  medium: "text-[color:var(--warn)]",
  high: "text-danger",
};

export function ActionButton({ item }: { item: ActionItem }) {
  return (
    <div className="flex cursor-not-allowed items-center justify-between gap-3 rounded-[10px] border border-border bg-card px-3 py-2 opacity-60">
      <div className="flex items-center gap-2 min-w-0">
        <Lock size={12} className="shrink-0 text-fg-3" />
        <div className="flex flex-col min-w-0">
          <span className="text-xs text-foreground">{item.label}</span>
          {item.description && (
            <span className="truncate text-[10px] text-muted-foreground">{item.description}</span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        <span className={`font-mono text-[10px] ${dangerColors[item.danger] ?? "text-muted-foreground"}`}>
          {item.danger}
        </span>
        <Badge variant="muted">V2</Badge>
      </div>
    </div>
  );
}
