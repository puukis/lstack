import { AlertCircle, Folder, Loader2 } from "lucide-react";
import { useOverview } from "@/api/queries";
import { StatusCard } from "@/components/cards/StatusCard";
import { MetricCard } from "@/components/cards/MetricCard";
import { Card, CardTitle, Row } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { fmtTs } from "@/lib/format";
import {
  HooksCard,
  SkillsCard,
  AgentsCard,
  HealthCard,
  ParallelCard,
  DoctorCard,
} from "@/components/cards/SectionCard";

export function OverviewPage() {
  const { data, isLoading, isError, error } = useOverview();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-muted-foreground">
        <Loader2 size={18} className="animate-spin" />
        <span className="text-sm">Loading overview…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2 rounded-[10px] border border-danger bg-danger-dim px-4 py-3 text-sm text-danger">
        <AlertCircle size={16} className="shrink-0" />
        {error instanceof Error ? error.message : "Failed to load overview"}
      </div>
    );
  }

  if (!data) return null;

  const memMetrics = [
    { name: "Observations", value: data.memory.observations_count, color: "var(--accent)" },
    { name: "Learnings", value: data.memory.learnings_count, color: "var(--warn)" },
  ];

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardTitle>
          <span className="flex items-center gap-2">
            <Folder size={13} />
            Workspace
          </span>
        </CardTitle>
        <div className="grid gap-3 md:grid-cols-2">
          <Row label="Root">
            <span className="font-mono">{data.project.root_path_display}</span>
          </Row>
          <Row label="Generated">
            <span className="font-mono">{fmtTs(data.generated_at)}</span>
          </Row>
          <Row label="Runtime">{data.runtime.shell_mode}</Row>
          <Row label="Read-only">
            {data.read_only ? <Badge variant="pass">enabled</Badge> : <StatusBadge status="warn" />}
          </Row>
        </div>
      </Card>
      <StatusCard install={data.install} runtime={data.runtime} />
      <HooksCard hooks={data.hooks} />
      <MetricCard title="Memory" metrics={memMetrics} />
      <SkillsCard skills={data.skills} />
      <AgentsCard agents={data.agents} />
      <HealthCard health={data.health} />
      <ParallelCard parallel={data.parallel} />
      <DoctorCard doctor={data.doctor} />
    </div>
  );
}
