import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/cn";
import type { TradeRow } from "@/lib/data";
import { fmtUsd, fmtDateTime } from "@/lib/data";

export function TradesTable({ trades }: { trades: TradeRow[] }) {
  if (trades.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-[var(--border)] p-6 text-center text-[12px] text-[var(--text-tertiary)]">
        No simulated trades to display.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto -mx-2 px-2 scrollbar-thin">
      <table className="w-full text-[12.5px] tabular">
        <thead>
          <tr className="text-left text-[10.5px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
            <th className="font-medium px-3 py-2.5">Time (UTC)</th>
            <th className="font-medium px-3 py-2.5">Symbol</th>
            <th className="font-medium px-3 py-2.5">Side</th>
            <th className="font-medium px-3 py-2.5 text-right">Size</th>
            <th className="font-medium px-3 py-2.5 text-right">Entry</th>
            <th className="font-medium px-3 py-2.5 text-right">Exit</th>
            <th className="font-medium px-3 py-2.5 text-right">PnL</th>
            <th className="font-medium px-3 py-2.5 text-right">PnL %</th>
            <th className="font-medium px-3 py-2.5">Exit reason</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, idx) => {
            const positive = t.pnl_usd > 0;
            const negative = t.pnl_usd < 0;
            return (
              <tr
                key={`${t.symbol}-${t.ts}-${idx}`}
                className="border-t border-[var(--border)] hover:bg-[var(--surface-2)]/50 transition-colors"
              >
                <td className="px-3 py-2.5 text-[var(--text-secondary)] whitespace-nowrap">
                  {fmtDateTime(t.ts)}
                </td>
                <td className="px-3 py-2.5 font-medium text-[var(--text-primary)]">
                  {t.symbol}
                </td>
                <td className="px-3 py-2.5">
                  <span
                    className={cn(
                      "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium",
                      "bg-[color:var(--info)]/10 text-[var(--info)]",
                    )}
                  >
                    <ArrowUpRight className="h-3 w-3" strokeWidth={2.4} />
                    {t.action}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-right text-[var(--text-secondary)]">
                  {fmtUsd(t.size_usd)}
                </td>
                <td className="px-3 py-2.5 text-right text-[var(--text-secondary)]">
                  ${t.fill_price.toFixed(2)}
                </td>
                <td className="px-3 py-2.5 text-right text-[var(--text-secondary)]">
                  ${t.exit_price.toFixed(2)}
                </td>
                <td
                  className={cn(
                    "px-3 py-2.5 text-right font-semibold whitespace-nowrap",
                    positive && "text-[var(--success)]",
                    negative && "text-[var(--warning)]",
                    !positive && !negative && "text-[var(--text-secondary)]",
                  )}
                >
                  <span className="inline-flex items-center gap-1 justify-end">
                    {positive ? (
                      <ArrowUpRight className="h-3.5 w-3.5" strokeWidth={2.2} />
                    ) : negative ? (
                      <ArrowDownRight className="h-3.5 w-3.5" strokeWidth={2.2} />
                    ) : null}
                    {fmtUsd(t.pnl_usd, { signed: true })}
                  </span>
                </td>
                <td
                  className={cn(
                    "px-3 py-2.5 text-right whitespace-nowrap",
                    positive && "text-[var(--success)]",
                    negative && "text-[var(--warning)]",
                    !positive && !negative && "text-[var(--text-secondary)]",
                  )}
                >
                  {t.pnl_pct >= 0 ? "+" : ""}
                  {t.pnl_pct.toFixed(2)}%
                </td>
                <td className="px-3 py-2.5 text-[var(--text-secondary)]">
                  <code className="text-[11px] text-[var(--text-tertiary)] bg-[var(--surface-2)] px-1.5 py-0.5 rounded">
                    {t.exit_reason}
                  </code>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
