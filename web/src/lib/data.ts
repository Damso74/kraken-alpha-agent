import backtest from "../../public/data/backtest_xstocks_30d.json";

export type EquityPoint = {
  ts: string;
  equity_usd: number;
};

export type TradeRow = {
  ts: string;
  exit_ts?: string | null;
  symbol: string;
  action: "BUY" | "SELL" | string;
  size_usd: number;
  qty: number;
  fill_price: number;
  exit_price: number;
  exit_reason: string;
  pnl_usd: number;
  pnl_pct: number;
  duration_min: number | null;
};

export type SymbolSummary = {
  symbol: string;
  trades_count: number;
  buy_count: number;
  sell_count: number;
  wins: number;
  losses: number;
  net_pnl_usd: number;
  net_pnl_pct: number;
  max_drawdown_pct: number;
  last_price: number;
};

export type BacktestSummary = {
  starting_capital_usd: number;
  ending_capital_usd: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  max_drawdown_usd: number;
  max_drawdown_pct: number;
  total_trades: number;
  buy_count: number;
  sell_count: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: number;
  per_trade_sharpe: number | null;
  best_symbol: string | null;
  worst_symbol: string | null;
};

export type RejectionReason = {
  reason: string;
  count: number;
};

export type BacktestPayload = {
  generated_at: string;
  profile: string;
  source: string;
  engine: string;
  interval_minutes: number;
  period: {
    start: string | null;
    end: string | null;
    days: number;
    ohlc_days?: number;
    active_days?: number;
  };
  universe: string[];
  summary: BacktestSummary;
  by_symbol: SymbolSummary[];
  equity_curve: EquityPoint[];
  trades: TradeRow[];
  rejection_reasons_top: RejectionReason[];
  rejections: {
    live_xstocks_spot: string;
    live_xstocks_perps: string;
    btc_perp_control: string;
    account_class: string;
    verified_at: string;
  };
  tests: {
    passed: number;
    failed: number;
    duration_s: number;
  };
  notes: string[];
};

export const data = backtest as unknown as BacktestPayload;

export function fmtUsd(value: number, opts: { signed?: boolean; decimals?: number } = {}): string {
  const decimals = opts.decimals ?? 2;
  const sign = opts.signed && value > 0 ? "+" : value < 0 ? "-" : "";
  const abs = Math.abs(value);
  return `${sign}$${abs.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  })}`;
}

export function fmtPct(value: number, opts: { signed?: boolean; decimals?: number } = {}): string {
  const decimals = opts.decimals ?? 2;
  const sign = opts.signed && value > 0 ? "+" : value < 0 ? "" : "";
  return `${sign}${value.toFixed(decimals)}%`;
}

export function fmtDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "UTC",
  });
}

export function fmtDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "2-digit",
    year: "numeric",
    timeZone: "UTC",
  });
}

export function topTradesByAbsPnl(rows: TradeRow[], limit = 10): TradeRow[] {
  return [...rows]
    .sort((a, b) => Math.abs(b.pnl_usd) - Math.abs(a.pnl_usd))
    .slice(0, limit);
}
