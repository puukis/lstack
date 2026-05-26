import { cn } from "@/lib/cn";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "secondary" | "ghost" | "outline" | "destructive";
  size?: "sm" | "default";
}

export function Button({ variant = "default", size = "default", className, children, ...props }: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-[7px] font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-[var(--accent-dim)] disabled:cursor-not-allowed disabled:opacity-50",
        variant === "default" && "border border-transparent bg-foreground text-background hover:opacity-90",
        variant === "secondary" && "border border-border bg-secondary text-secondary-foreground hover:border-border-strong",
        variant === "ghost" && "text-muted-foreground hover:bg-panel-subtle hover:text-foreground",
        variant === "outline" && "border border-border bg-card text-foreground hover:border-border-strong hover:bg-panel-subtle",
        variant === "destructive" && "border border-transparent bg-danger text-white hover:opacity-90",
        size === "sm" && "gap-1.5 px-2.5 py-1 text-xs",
        size === "default" && "gap-2 px-3 py-1.5 text-sm",
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
