import { Card, CardTitle, Row } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { cn } from "@/lib/cn";
import { AlertCircle, Check } from "lucide-react";
import type { HooksSection, SkillsSection, AgentsSection, HealthSection, ParallelSection, DoctorSection } from "@/api/types";

const HOOK_LABELS: Array<[keyof HooksSection, string]> = [
  ["session_start", "session-start"],
  ["pre_tool", "pre-tool"],
  ["post_tool", "post-tool"],
  ["pre_compact", "pre-compact"],
  ["stop", "stop"],
];

export function HooksCard({ hooks }: { hooks: HooksSection }) {
  return (
    <Card>
      <CardTitle>Hooks</CardTitle>
      {HOOK_LABELS.map(([key, label]) => {
        const entry = hooks[key] as { exists: boolean; syntax?: string } | undefined;
        return (
          <Row key={key} label={label}>
            {entry?.exists ? <StatusBadge status={entry.syntax ?? "unknown"} /> : <Badge variant="fail">missing</Badge>}
          </Row>
        );
      })}
      <Row label="statusline">
        {hooks.statusline?.exists ? <Badge variant="info">present</Badge> : <Badge variant="muted">missing</Badge>}
      </Row>
    </Card>
  );
}

const HIGHLIGHTED = new Set(["receipt", "passport", "work"]);

export function SkillsCard({ skills }: { skills: SkillsSection }) {
  return (
    <Card>
      <CardTitle>Skills</CardTitle>
      <Row label="Count">{skills.count}</Row>
      <div className="flex flex-wrap gap-1 mt-1">
        {skills.items.map((s) => (
          <span
            key={s}
            className={cn(
              "rounded-[7px] border px-2 py-0.5 font-mono text-[11px]",
              HIGHLIGHTED.has(s)
                ? "border-transparent bg-accent-dim text-accent-foreground"
                : "border-border bg-panel-subtle text-muted-foreground"
            )}
          >
            {s}
          </span>
        ))}
      </div>
    </Card>
  );
}

export function AgentsCard({ agents }: { agents: AgentsSection }) {
  return (
    <Card>
      <CardTitle>Agents</CardTitle>
      <Row label="Count">{agents.count}</Row>
      <div className="flex flex-wrap gap-1 mt-1">
        {agents.items.map((a) => (
          <span key={a} className="rounded-[7px] border border-border bg-panel-subtle px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
            {a}
          </span>
        ))}
      </div>
    </Card>
  );
}

export function HealthCard({ health }: { health: HealthSection }) {
  return (
    <Card>
      <CardTitle>Health</CardTitle>
      <Row label="Available">{health.available ? <Badge variant="info">yes</Badge> : <Badge variant="muted">no</Badge>}</Row>
      <Row label="Latest saved">{health.latest_saved ?? "none"}</Row>
      <p className="text-xs text-muted-foreground">{health.note}</p>
    </Card>
  );
}

export function ParallelCard({ parallel }: { parallel: ParallelSection }) {
  return (
    <Card>
      <CardTitle>Parallel Worktrees</CardTitle>
      <Row label="Active"><Badge variant={parallel.active > 0 ? "running" : "muted"}>{parallel.active}</Badge></Row>
      <Row label="Done"><Badge variant={parallel.done > 0 ? "pass" : "muted"}>{parallel.done}</Badge></Row>
      <Row label="Failed"><Badge variant={parallel.failed > 0 ? "fail" : "muted"}>{parallel.failed}</Badge></Row>
      <Row label="Legacy cmd"><code className="text-[11px] text-accent-foreground">{parallel.legacy_command}</code></Row>
      {parallel.worktrees.map((w) => (
        <div key={w.name} className="mt-0.5 flex items-center justify-between gap-2 text-xs">
          <span className="truncate font-mono text-muted-foreground">{w.name}</span>
          <div className="flex items-center gap-1 shrink-0">
            <span className="text-[10px] text-fg-3">{w.branch}</span>
            <StatusBadge status={w.status} />
          </div>
        </div>
      ))}
    </Card>
  );
}

export function DoctorCard({ doctor }: { doctor: DoctorSection }) {
  if (doctor.available === false) {
    return (
      <Card>
        <CardTitle>Doctor</CardTitle>
        <p className="text-xs text-danger">{doctor.error ?? "Unavailable"}</p>
      </Card>
    );
  }
  return (
    <Card>
      <CardTitle>Doctor</CardTitle>
      <Row label="Status"><StatusBadge status={doctor.status} /></Row>
      {doctor.failures?.length > 0 && (
        <ul className="flex flex-col gap-0.5 mt-1">
          {doctor.failures.map((f) => (
            <li key={f} className="flex items-start gap-1.5 font-mono text-[11px] text-danger">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              {f}
            </li>
          ))}
        </ul>
      )}
      {doctor.warnings?.length > 0 && (
        <ul className="flex flex-col gap-0.5 mt-1">
          {doctor.warnings.map((w) => (
            <li key={w} className="flex items-start gap-1.5 font-mono text-[11px] text-[color:var(--warn)]">
              <AlertCircle size={12} className="mt-0.5 shrink-0" />
              {w}
            </li>
          ))}
        </ul>
      )}
      {!doctor.failures?.length && !doctor.warnings?.length && (
        <p className="mt-1 flex items-center gap-1.5 text-xs text-accent-foreground">
          <Check size={13} />
          All checks passed
        </p>
      )}
    </Card>
  );
}
