import { Card, CardTitle } from "@/components/ui/card";
import { BarChart, Bar, XAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";
import { fmtCount } from "@/lib/format";

export interface MetricEntry {
  name: string;
  value: number;
  color: string;
}

export function MetricCard({ title, metrics }: { title: string; metrics: MetricEntry[] }) {
  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      <div className="flex gap-4 flex-wrap">
        {metrics.map((m) => (
          <div key={m.name} className="flex flex-col">
            <span className="text-2xl font-semibold leading-none" style={{ color: m.color }}>
              {fmtCount(m.value)}
            </span>
            <span className="mt-1 text-xs text-muted-foreground">{m.name}</span>
          </div>
        ))}
      </div>
      {metrics.some((m) => m.value > 0) && (
        <div className="mt-1 h-20" aria-label={`${title} chart`}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={metrics} barSize={22} accessibilityLayer>
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "var(--fg-3)" }} axisLine={false} tickLine={false} />
              <Tooltip
                contentStyle={{ background: "var(--panel)", border: "1px solid var(--border-strong)", borderRadius: "7px", fontSize: "12px", color: "var(--fg)" }}
                itemStyle={{ color: "var(--fg-2)" }}
              />
              <Bar dataKey="value" radius={[7, 7, 0, 0]}>
                {metrics.map((m, i) => <Cell key={i} fill={m.color} fillOpacity={0.8} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <table className="sr-only">
            <caption>{title}</caption>
            <tbody>
              {metrics.map((m) => (
                <tr key={m.name}>
                  <th scope="row">{m.name}</th>
                  <td>{fmtCount(m.value)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
