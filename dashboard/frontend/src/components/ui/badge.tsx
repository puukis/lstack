import { cn } from "@/lib/cn";

type Variant = "pass" | "warn" | "fail" | "info" | "muted" | "running";

const variants: Record<Variant, string> = {
  pass: "bg-accent-dim text-accent-foreground border-transparent",
  warn: "bg-warn-dim text-[color:var(--warn)] border-transparent",
  fail: "bg-danger-dim text-danger border-transparent",
  info: "bg-panel-subtle text-foreground border-border",
  muted: "bg-panel-subtle text-muted-foreground border-border",
  running: "bg-accent-dim text-accent-foreground border-transparent",
};

export function Badge({
  variant = "muted",
  children,
  className,
}: {
  variant?: Variant;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-[7px] border px-2 py-0.5 text-[11px] font-medium leading-4",
        variants[variant],
        className
      )}
    >
      {children}
    </span>
  );
}

const statusMap: Record<string, Variant> = {
  pass: "pass", ok: "pass", done: "pass", valid: "pass",
  warn: "warn", warning: "warn", invalid: "warn",
  fail: "fail", failed: "fail", error: "fail", missing: "fail",
  running: "running",
  unknown: "muted",
};

export function StatusBadge({ status }: { status?: string | null }) {
  if (!status) return <Badge variant="muted">?</Badge>;
  const v = statusMap[status.toLowerCase()] ?? "muted";
  return <Badge variant={v}>{status}</Badge>;
}
