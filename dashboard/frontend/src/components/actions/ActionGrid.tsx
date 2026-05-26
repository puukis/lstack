import { ActionButton } from "./ActionButton";
import { Badge } from "@/components/ui/badge";
import type { ActionsSection } from "@/api/types";

export function ActionGrid({ actions }: { actions: ActionsSection }) {
  const byCategory = actions.items.reduce<Record<string, typeof actions.items>>((acc, item) => {
    const cat = item.category ?? "other";
    acc[cat] = [...(acc[cat] ?? []), item];
    return acc;
  }, {});

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="muted">{actions.mode}</Badge>
        <span className="text-xs text-muted-foreground">
          Interactive controls are planned for a later version. All buttons are disabled in V1.
        </span>
      </div>
      {Object.entries(byCategory).map(([cat, items]) => (
        <div key={cat}>
          <h3 className="mb-2 text-[10px] font-semibold uppercase text-fg-3">
            {cat}
          </h3>
          <div className="flex flex-col gap-1.5">
            {items.map((item) => <ActionButton key={item.id} item={item} />)}
          </div>
        </div>
      ))}
    </div>
  );
}
