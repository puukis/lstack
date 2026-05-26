import { Loader2, AlertCircle } from "lucide-react";
import { useLBrain } from "@/api/queries";
import { Card, CardTitle, Row, SectionLabel } from "@/components/ui/card";
import { Badge, StatusBadge } from "@/components/ui/badge";
import { MetricCard } from "@/components/cards/MetricCard";

export function LBrainPage() {
  const { data, isLoading, isError, error } = useLBrain();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-muted-foreground">
        <Loader2 size={16} className="animate-spin" />
        <span className="text-sm">Loading LBrain…</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2 rounded-[10px] border border-danger bg-danger-dim px-4 py-3 text-sm text-danger">
        <AlertCircle size={16} className="shrink-0" />
        {error instanceof Error ? error.message : "Failed to load LBrain"}
      </div>
    );
  }

  if (!data) return null;

  if (data.available === false) {
    return (
      <Card>
        <CardTitle>LBrain</CardTitle>
        <p className="text-xs text-danger">{data.error ?? "Not available"}</p>
      </Card>
    );
  }

  const pp = data.passport;
  const fw = data.firewall;
  const rc = data.receipts;
  const ct = data.contracts;
  const dc = data.decisions;
  const fa = data.failed_attempts;
  const cap = data.capture;
  const gov = data.context_governor;
  const dr = data.doctor;

  const captureMetrics = cap
    ? [
        { name: "Events", value: cap.events_count, color: "var(--accent)" },
        { name: "Pending", value: cap.pending_candidates_count, color: "var(--warn)" },
        { name: "Promoted", value: cap.promoted_candidates_count, color: "var(--accent-text)" },
      ]
    : [];

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card>
        <CardTitle>Repo Passport</CardTitle>
        <Row label="Available">
          {pp?.available ? <Badge variant="pass">yes</Badge> : <Badge variant="muted">no</Badge>}
        </Row>
        {pp?.available && pp.stack && (
          <Row label="Stack">
            <div className="flex flex-wrap gap-1 justify-end">
              {pp.stack.slice(0, 6).map((s) => (
                <span key={s} className="rounded-[7px] border border-border bg-panel-subtle px-2 py-0.5 text-[10px] text-muted-foreground">
                  {s}
                </span>
              ))}
            </div>
          </Row>
        )}
        {pp?.available && pp.package_manager && (
          <Row label="Package mgr">{pp.package_manager}</Row>
        )}
      </Card>

      <Card>
        <CardTitle>Change Receipts</CardTitle>
        <Row label="Open">
          {rc?.open ? (
            <Badge variant="info">{(rc.open.title ?? "open").slice(0, 30)}</Badge>
          ) : (
            <Badge variant="muted">none</Badge>
          )}
        </Row>
        <Row label="Recent count">{rc?.recent?.length ?? 0}</Row>
      </Card>

      <Card>
        <CardTitle>Decisions & Contracts</CardTitle>
        <SectionLabel>Decisions</SectionLabel>
        <Row label="Active">{dc?.active_count ?? 0}</Row>
        <SectionLabel>Task Contracts</SectionLabel>
        <Row label="Active">{ct?.active_count ?? 0}</Row>
      </Card>

      <Card>
        <CardTitle>Failed Attempts</CardTitle>
        <Row label="Total count">{fa?.count ?? 0}</Row>
      </Card>

      {/* Capture */}
      {cap && <MetricCard title="Capture" metrics={captureMetrics} />}

      <Card>
        <CardTitle>AI Mistake Firewall</CardTitle>
        <Row label="Status"><StatusBadge status={fw?.status} /></Row>
        <Row label="Warnings">{fw?.warning_count ?? 0}</Row>
      </Card>

      {/* Context Governor */}
      <Card>
        <CardTitle>Context Governor</CardTitle>
        <Row label="Items">
          {gov?.count ?? (gov?.items ? gov.items.length : 0)}
        </Row>
      </Card>

      {dr && (
        <Card>
          <CardTitle>LBrain Doctor</CardTitle>
          <Row label="Status"><StatusBadge status={dr.status} /></Row>
          {dr.failures?.length > 0 && (
            <ul className="flex flex-col gap-0.5 mt-1">
              {dr.failures.map((f) => (
                <li key={f} className="flex items-start gap-1.5 font-mono text-[11px] text-danger">
                  <AlertCircle size={12} className="mt-0.5 shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
          )}
          {dr.warnings?.length > 0 && (
            <ul className="flex flex-col gap-0.5 mt-1">
              {dr.warnings.map((w) => (
                <li key={w} className="flex items-start gap-1.5 font-mono text-[11px] text-[color:var(--warn)]">
                  <AlertCircle size={12} className="mt-0.5 shrink-0" />
                  {w}
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}
    </div>
  );
}
