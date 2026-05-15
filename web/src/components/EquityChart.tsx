"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { EquityPoint } from "@/lib/data";

type ChartPoint = {
  ts: string;
  date: string;
  equity_usd: number;
  pnl_usd: number;
};

function formatTs(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    timeZone: "UTC",
  });
}

export function EquityChart({
  points,
  startingCapital,
  positive,
  height,
  className,
}: {
  points: EquityPoint[];
  startingCapital: number;
  positive: boolean;
  height?: number;
  className?: string;
}) {
  const data: ChartPoint[] = points.map((p) => ({
    ts: p.ts,
    date: formatTs(p.ts),
    equity_usd: Number(p.equity_usd.toFixed(4)),
    pnl_usd: Number((p.equity_usd - startingCapital).toFixed(4)),
  }));

  const stroke = positive ? "var(--success)" : "var(--warning)";
  const fillId = positive ? "equityFillUp" : "equityFillDown";

  if (data.length === 0) {
    return (
      <div
        className={`grid place-items-center text-[12px] text-[var(--text-tertiary)] border border-dashed border-[var(--border)] rounded-md ${className ?? ""}`}
        style={height ? { height } : undefined}
      >
        No equity points to display.
      </div>
    );
  }

  const minEq = Math.min(...data.map((d) => d.equity_usd), startingCapital);
  const maxEq = Math.max(...data.map((d) => d.equity_usd), startingCapital);
  const pad = Math.max((maxEq - minEq) * 0.15, 1);

  return (
    <div
      className={className}
      style={
        height
          ? { width: "100%", height }
          : { width: "100%", height: "100%", minHeight: 180 }
      }
    >
      <ResponsiveContainer width="100%" height="100%" minHeight={180}>
        <AreaChart data={data} margin={{ top: 16, right: 12, left: 4, bottom: 0 }}>
          <defs>
            <linearGradient id="equityFillUp" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--success)" stopOpacity={0.32} />
              <stop offset="100%" stopColor="var(--success)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="equityFillDown" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--warning)" stopOpacity={0.32} />
              <stop offset="100%" stopColor="var(--warning)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke="var(--border)" strokeDasharray="3 6" vertical={false} />
          <XAxis
            dataKey="date"
            stroke="var(--text-tertiary)"
            tickLine={false}
            axisLine={{ stroke: "var(--border)" }}
            tick={{ fontSize: 11, fill: "var(--text-tertiary)" }}
            minTickGap={36}
          />
          <YAxis
            stroke="var(--text-tertiary)"
            tickLine={false}
            axisLine={false}
            tick={{ fontSize: 11, fill: "var(--text-tertiary)" }}
            domain={[minEq - pad, maxEq + pad]}
            tickFormatter={(v: number) => `$${v.toLocaleString("en-US", { maximumFractionDigits: 0 })}`}
            width={60}
          />
          <Tooltip
            cursor={{ stroke: "var(--border-strong)", strokeDasharray: "3 3" }}
            contentStyle={{
              background: "var(--surface-1)",
              border: "1px solid var(--border-strong)",
              borderRadius: 10,
              fontSize: 12,
              padding: "10px 12px",
              boxShadow: "0 12px 32px -16px rgba(0,0,0,0.6)",
            }}
            labelStyle={{ color: "var(--text-secondary)", marginBottom: 4 }}
            itemStyle={{ color: "var(--text-primary)" }}
            formatter={(value, name) => {
              const num = typeof value === "number" ? value : Number(value ?? 0);
              if (name === "equity_usd") {
                return [
                  `$${num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                  "Equity",
                ];
              }
              return [String(value ?? ""), String(name ?? "")];
            }}
          />
          <Area
            type="monotone"
            dataKey="equity_usd"
            stroke={stroke}
            strokeWidth={2}
            fill={`url(#${fillId})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
