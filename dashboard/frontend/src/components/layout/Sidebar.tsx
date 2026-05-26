import { NavLink } from "react-router-dom";
import { Activity, BrainCircuit, Database, Home, ReceiptText } from "lucide-react";
import { cn } from "@/lib/cn";

const NAV_GROUPS = [
  {
    label: "System",
    items: [
      { to: "/", label: "Overview", icon: Home, end: true },
      { to: "/actions", label: "Actions", icon: Activity, end: false },
    ],
  },
  {
    label: "LBrain",
    items: [
      { to: "/memory", label: "Memory", icon: Database, end: false },
      { to: "/lbrain", label: "LBrain", icon: BrainCircuit, end: false },
      { to: "/audit", label: "Audit", icon: ReceiptText, end: false },
    ],
  },
];

export function Sidebar() {
  return (
    <aside className="flex w-full shrink-0 flex-col gap-4 border-b border-border bg-card px-3 py-3 md:min-h-screen md:w-60 md:border-b-0 md:border-r md:px-4 md:py-5">
      <div className="flex items-center gap-3 px-1">
        <div className="grid size-8 place-items-center rounded-[9px] bg-accent text-sm font-bold text-stone-950">
          L
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold leading-tight text-foreground">LStack</p>
          <p className="text-xs leading-tight text-muted-foreground">Dashboard</p>
        </div>
      </div>
      <nav className="flex gap-2 overflow-x-auto md:flex-col md:gap-5" aria-label="Primary">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="flex shrink-0 gap-2 md:flex-col md:gap-1">
            <p className="hidden px-2 text-[10px] font-semibold uppercase text-fg-3 md:block">
              {group.label}
            </p>
            {group.items.map(({ to, label, icon: Icon, end }) => (
              <NavLink
                key={to}
                to={to}
                end={end}
                className={({ isActive }) =>
                  cn(
                    "flex items-center gap-2 rounded-[7px] border px-2.5 py-1.5 text-xs font-medium transition-colors",
                    isActive
                      ? "border-border-strong bg-panel-subtle text-foreground"
                      : "border-transparent text-muted-foreground hover:bg-panel-subtle hover:text-foreground"
                  )
                }
              >
                <Icon size={14} />
                {label}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="mt-auto hidden border-t border-border px-1 pt-4 md:block">
        <p className="text-[11px] text-muted-foreground">Read-only local console</p>
      </div>
    </aside>
  );
}
