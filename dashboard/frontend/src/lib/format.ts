export function fmtTs(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

export function fmtCount(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function truncate(s: string, n = 50): string {
  return s.length > n ? s.slice(0, n) + "…" : s;
}
