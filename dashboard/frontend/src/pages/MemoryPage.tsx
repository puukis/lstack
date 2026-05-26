import { useMemo, useState } from "react";
import { AlertCircle, BookOpen, Database, Loader2 } from "lucide-react";
import { useMemory } from "@/api/queries";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardTitle, Row } from "@/components/ui/card";
import { fmtCount, fmtTs, truncate } from "@/lib/format";
import { cn } from "@/lib/cn";
import type { LearningItem, ObservationItem } from "@/api/types";

type MemoryMode = "observations" | "learnings";

function ScopeBadge({ scope }: { scope: ObservationItem["scope"] }) {
  const variant = scope === "project" ? "pass" : scope === "global" ? "info" : "muted";
  return <Badge variant={variant}>{scope}</Badge>;
}

function EmptyState({ mode }: { mode: MemoryMode }) {
  const Icon = mode === "observations" ? Database : BookOpen;
  return (
    <Card className="items-center py-10 text-center">
      <Icon size={24} className="text-fg-3" />
      <p className="text-sm font-medium text-foreground">No {mode} found</p>
      <p className="max-w-sm text-xs text-muted-foreground">
        The memory database is reachable, but this table has no rows in the current local store.
      </p>
    </Card>
  );
}

function ObservationDetail({ item }: { item: ObservationItem }) {
  return (
    <Card className="min-h-[360px]">
      <CardTitle>Observation {item.id}</CardTitle>
      <div className="grid gap-3 md:grid-cols-2">
        <Row label="Scope"><ScopeBadge scope={item.scope} /></Row>
        <Row label="Created"><span className="font-mono">{fmtTs(item.created_at)}</span></Row>
        <Row label="Session"><span className="font-mono">{item.session_id}</span></Row>
        <Row label="Project"><span className="font-mono">{item.project}</span></Row>
      </div>
      {item.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {item.tags.map((tag) => <Badge key={tag} variant="muted">{tag}</Badge>)}
        </div>
      )}
      <pre className="whitespace-pre-wrap rounded-[10px] border border-border bg-panel-subtle p-3 font-mono text-xs leading-5 text-foreground">
        {item.content}
      </pre>
    </Card>
  );
}

function LearningDetail({ item }: { item: LearningItem }) {
  return (
    <Card className="min-h-[360px]">
      <CardTitle>Learning {item.id}</CardTitle>
      <div className="grid gap-3 md:grid-cols-2">
        <Row label="Key"><span className="font-mono">{item.key}</span></Row>
        <Row label="Type"><Badge variant="info">{item.type}</Badge></Row>
        <Row label="Scope"><ScopeBadge scope={item.scope} /></Row>
        <Row label="Confidence">{item.confidence}/10</Row>
        <Row label="Source">{item.source}</Row>
        <Row label="Trusted">{item.trusted ? <Badge variant="pass">yes</Badge> : <Badge variant="muted">no</Badge>}</Row>
        <Row label="Updated"><span className="font-mono">{fmtTs(item.updated_at)}</span></Row>
        <Row label="Created"><span className="font-mono">{fmtTs(item.created_at)}</span></Row>
      </div>
      {(item.tags.length > 0 || item.files.length > 0) && (
        <div className="flex flex-wrap gap-1">
          {item.tags.map((tag) => <Badge key={tag} variant="muted">{tag}</Badge>)}
          {item.files.map((file) => <Badge key={file} variant="info">{file}</Badge>)}
        </div>
      )}
      <pre className="whitespace-pre-wrap rounded-[10px] border border-border bg-panel-subtle p-3 font-mono text-xs leading-5 text-foreground">
        {item.insight}
      </pre>
    </Card>
  );
}

function ObservationRow({
  item,
  active,
  onSelect,
}: {
  item: ObservationItem;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col gap-1 rounded-[10px] border p-3 text-left transition-colors",
        active ? "border-border-strong bg-panel-subtle" : "border-border bg-card hover:bg-panel-subtle"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted-foreground">#{item.id}</span>
        <ScopeBadge scope={item.scope} />
      </div>
      <span className="text-sm text-foreground">{truncate(item.content, 120)}</span>
      <span className="font-mono text-[11px] text-fg-3">{fmtTs(item.created_at)}</span>
    </button>
  );
}

function LearningRow({
  item,
  active,
  onSelect,
}: {
  item: LearningItem;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "flex w-full flex-col gap-1 rounded-[10px] border p-3 text-left transition-colors",
        active ? "border-border-strong bg-panel-subtle" : "border-border bg-card hover:bg-panel-subtle"
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-xs text-foreground">{item.key}</span>
        <Badge variant="info">{item.type}</Badge>
      </div>
      <span className="text-sm text-foreground">{truncate(item.insight, 120)}</span>
      <span className="font-mono text-[11px] text-fg-3">{fmtTs(item.updated_at)}</span>
    </button>
  );
}

export function MemoryPage() {
  const { data, isLoading, isError, error } = useMemory();
  const [mode, setMode] = useState<MemoryMode>("observations");
  const [selectedObservationId, setSelectedObservationId] = useState<number | null>(null);
  const [selectedLearningId, setSelectedLearningId] = useState<number | null>(null);

  const selectedObservation = useMemo(() => {
    if (!data?.observations.length) return null;
    return data.observations.find((item) => item.id === selectedObservationId) ?? data.observations[0];
  }, [data?.observations, selectedObservationId]);

  const selectedLearning = useMemo(() => {
    if (!data?.learnings.length) return null;
    return data.learnings.find((item) => item.id === selectedLearningId) ?? data.learnings[0];
  }, [data?.learnings, selectedLearningId]);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-muted-foreground">
        <Loader2 size={16} className="animate-spin" />
        <span className="text-sm">Loading memory...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex items-center gap-2 rounded-[10px] border border-danger bg-danger-dim px-4 py-3 text-sm text-danger">
        <AlertCircle size={16} className="shrink-0" />
        {error instanceof Error ? error.message : "Failed to load memory"}
      </div>
    );
  }

  if (!data) return null;

  if (!data.available) {
    return (
      <Card>
        <CardTitle>Memory</CardTitle>
        <p className="text-xs text-danger">{data.error ?? "Memory database is not available."}</p>
      </Card>
    );
  }

  const observationsActive = mode === "observations";
  const items = observationsActive ? data.observations : data.learnings;

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardTitle>Memory</CardTitle>
        <div className="grid gap-3 md:grid-cols-4">
          <Row label="Database">{data.db_reachable ? <Badge variant="pass">reachable</Badge> : <Badge variant="fail">missing</Badge>}</Row>
          <Row label="Observations">{fmtCount(data.observations_count)}</Row>
          <Row label="Learnings">{fmtCount(data.learnings_count)}</Row>
          <Row label="FTS">{data.fts_available ? <Badge variant="pass">enabled</Badge> : <Badge variant="muted">off</Badge>}</Row>
        </div>
      </Card>

      <div className="flex flex-wrap gap-2">
        <Button
          variant={observationsActive ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("observations")}
        >
          <Database size={14} />
          Observations
        </Button>
        <Button
          variant={!observationsActive ? "default" : "outline"}
          size="sm"
          onClick={() => setMode("learnings")}
        >
          <BookOpen size={14} />
          Learnings
        </Button>
      </div>

      {items.length === 0 ? (
        <EmptyState mode={mode} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[minmax(280px,420px)_1fr]">
          <div className="flex max-h-[680px] flex-col gap-2 overflow-auto pr-1">
            {observationsActive
              ? data.observations.map((item) => (
                  <ObservationRow
                    key={item.id}
                    item={item}
                    active={selectedObservation?.id === item.id}
                    onSelect={() => setSelectedObservationId(item.id)}
                  />
                ))
              : data.learnings.map((item) => (
                  <LearningRow
                    key={item.id}
                    item={item}
                    active={selectedLearning?.id === item.id}
                    onSelect={() => setSelectedLearningId(item.id)}
                  />
                ))}
          </div>
          {observationsActive
            ? selectedObservation && <ObservationDetail item={selectedObservation} />
            : selectedLearning && <LearningDetail item={selectedLearning} />}
        </div>
      )}
    </div>
  );
}
