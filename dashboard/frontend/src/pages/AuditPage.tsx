import { Loader2, AlertCircle, ScrollText } from "lucide-react";
import { useAudit } from "@/api/queries";
import { Card, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fmtTs, truncate } from "@/lib/format";
import type { AuditEntry } from "@/api/types";

function EntryRow({ entry }: { entry: AuditEntry }) {
  const isOk = entry.result === "ok" || entry.result === "success";
  return (
    <div className="flex items-start gap-3 border-b border-border py-2 text-xs last:border-0">
      <span className="w-36 shrink-0 font-mono text-[10px] text-fg-3">{fmtTs(entry.ts)}</span>
      <div className="flex flex-col gap-0.5 min-w-0">
        <span className="font-mono text-foreground">{entry.action_id}</span>
        {entry.error && <span className="text-[10px] text-danger">{truncate(entry.error, 80)}</span>}
      </div>
      <Badge variant={isOk ? "pass" : "fail"} className="ml-auto shrink-0">
        {entry.result}
      </Badge>
    </div>
  );
}

export function AuditPage() {
  const { data, isLoading, isError, error } = useAudit();

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
        {error instanceof Error ? error.message : "Failed to load audit log"}
      </div>
    );
  }

  const entries = data?.entries ?? [];

  return (
    <div className="max-w-4xl">
      <Card>
        <CardTitle>
          <span className="flex items-center gap-1.5">
            <ScrollText size={11} />
            Dashboard Audit Log
          </span>
        </CardTitle>
        {entries.length === 0 ? (
          <p className="py-4 text-center text-xs text-muted-foreground">
            No audit entries yet. Actions will be logged here in V2.
          </p>
        ) : (
          <div className="flex flex-col">
            {entries.map((e, i) => <EntryRow key={i} entry={e} />)}
          </div>
        )}
      </Card>
    </div>
  );
}
