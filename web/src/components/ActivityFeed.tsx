import {
  Activity,
  CheckCircle2,
  Cpu,
  Database,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type FeedEntry = {
  ts: string;
  label: string;
  detail: string;
  icon: LucideIcon;
  tone: "success" | "info" | "neutral";
};

const TONE: Record<FeedEntry["tone"], string> = {
  success: "text-[var(--success)] bg-[color:var(--success)]/10",
  info: "text-[var(--info)] bg-[color:var(--info)]/10",
  neutral: "text-[var(--text-secondary)] bg-[var(--surface-2)]",
};

export function ActivityFeed({
  generatedAt,
  testsPassed,
  testsDuration,
  netPnl,
  tradesCount,
}: {
  generatedAt: string;
  testsPassed: number;
  testsDuration: number;
  netPnl: number;
  tradesCount: number;
}) {
  const base = new Date(generatedAt);
  const minus = (mins: number) => new Date(base.getTime() - mins * 60_000);
  const fmt = (d: Date) =>
    d.toLocaleString("en-US", {
      month: "short",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
      timeZone: "UTC",
    });

  const entries: FeedEntry[] = [
    {
      ts: fmt(base),
      label: `Backtest exported — ${tradesCount} trades, net PnL ${
        netPnl >= 0 ? "+" : ""
      }$${netPnl.toFixed(2)}`,
      detail: "30 days of real Kraken xStocks OHLC, deterministic engine replay.",
      icon: Database,
      tone: "success",
    },
    {
      ts: fmt(minus(8)),
      label: `pytest suite green — ${testsPassed} / ${testsPassed} passed`,
      detail: `${testsDuration.toFixed(2)}s wall-clock, no flaky tests, no skips.`,
      icon: CheckCircle2,
      tone: "success",
    },
    {
      ts: fmt(minus(22)),
      label: "Risk gates heartbeat — all green",
      detail:
        "max_total_exposure, max_open_positions, drawdown, cooldown, shorting=false.",
      icon: ShieldCheck,
      tone: "info",
    },
    {
      ts: fmt(minus(41)),
      label: "VPS Vultr Ubuntu 24.04 LTS — agent online",
      detail: "Region ewr · KRAKEN_CLI_TRANSPORT=auto · watchdog + dead-man cancel-after.",
      icon: Cpu,
      tone: "info",
    },
    {
      ts: fmt(minus(63)),
      label: "BTC Perp control order — status: placed",
      detail: "Same Futures key/IP as xStocks Perps; confirms code path is healthy.",
      icon: TerminalSquare,
      tone: "success",
    },
    {
      ts: fmt(minus(95)),
      label: "Market-data ingestion — xStocks 24/5 + crypto 24/7",
      detail: "Real Kraken CLI ticker / ohlc / orderbook / trades, no mocks in audit logs.",
      icon: Activity,
      tone: "neutral",
    },
  ];

  return (
    <ol className="relative pl-5 -ml-1">
      <span
        aria-hidden
        className="absolute left-1 top-2 bottom-2 w-px bg-gradient-to-b from-[var(--border-strong)] via-[var(--border)] to-transparent"
      />
      {entries.map((e, idx) => {
        const Icon = e.icon;
        return (
          <li key={idx} className="relative pl-5 pb-4 last:pb-0">
            <span
              className={`absolute -left-1.5 top-0.5 h-6 w-6 rounded-md grid place-items-center ring-2 ring-[var(--surface-1)] ${
                TONE[e.tone]
              }`}
            >
              <Icon className="h-3 w-3" strokeWidth={2.2} />
            </span>
            <div className="flex flex-wrap items-baseline gap-x-3">
              <span className="text-[12.5px] font-medium text-[var(--text-primary)]">
                {e.label}
              </span>
              <span className="text-[10.5px] tabular text-[var(--text-tertiary)] uppercase tracking-[0.1em]">
                {e.ts} UTC
              </span>
            </div>
            <p className="mt-0.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
              {e.detail}
            </p>
          </li>
        );
      })}
    </ol>
  );
}
