import { Loader2, AlertCircle, ShieldAlert } from "lucide-react";
import { useActions } from "@/api/queries";
import { ActionGrid } from "@/components/actions/ActionGrid";
import { Card, CardTitle } from "@/components/ui/card";

export function ActionsPage() {
  const { data, isLoading, isError, error } = useActions();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-muted-foreground">
        <Loader2 size={16} className="animate-spin" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2 rounded-[10px] border border-danger bg-danger-dim px-4 py-3 text-sm text-danger">
        <AlertCircle size={16} className="shrink-0" />
        {error instanceof Error ? error.message : "Failed to load actions"}
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="flex max-w-4xl flex-col gap-4">
      <ActionGrid actions={data} />

      {data.v2_rules && (
        <Card>
          <CardTitle>
            <span className="flex items-center gap-1.5">
              <ShieldAlert size={11} />
              V2 Safety Rules
            </span>
          </CardTitle>
          <ul className="flex flex-col gap-0.5 mt-1">
            {data.v2_rules.map((r) => (
              <li key={r} className="font-mono text-[11px] text-muted-foreground">
                {r}
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
