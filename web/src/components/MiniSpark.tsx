"use client";

import { Area, AreaChart, ResponsiveContainer } from "recharts";
import type { EquityPoint } from "@/lib/data";

export function MiniSpark({
  points,
  positive,
  width = 200,
  height = 56,
}: {
  points: EquityPoint[];
  positive: boolean;
  width?: number;
  height?: number;
}) {
  const data = points.map((p) => ({ v: p.equity_usd }));
  const stroke = positive ? "var(--success)" : "var(--warning)";
  const fillId = positive ? "miniFillUp" : "miniFillDown";

  if (data.length === 0) {
    return (
      <div
        style={{ width, height }}
        className="grid place-items-center text-[10px] text-[var(--text-tertiary)] border border-dashed border-[var(--border)] rounded-md"
      >
        no data
      </div>
    );
  }

  return (
    <div style={{ width, height }}>
      <ResponsiveContainer
        width="100%"
        height="100%"
        minWidth={0}
        initialDimension={{ width, height }}
      >
        <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
          <defs>
            <linearGradient id="miniFillUp" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--success)" stopOpacity={0.4} />
              <stop offset="100%" stopColor="var(--success)" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="miniFillDown" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="var(--warning)" stopOpacity={0.4} />
              <stop offset="100%" stopColor="var(--warning)" stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="v"
            stroke={stroke}
            strokeWidth={1.6}
            fill={`url(#${fillId})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
