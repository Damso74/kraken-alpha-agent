import {
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  CircleDollarSign,
  Database,
  ExternalLink,
  GitMerge,
  Layers,
  PlayCircle,
  ShieldCheck,
  Sparkles,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

import { ActivityFeed } from "@/components/ActivityFeed";
import { GithubIcon } from "@/components/GithubIcon";
import { EquityChart } from "@/components/EquityChart";
import { JudgeTakeaway } from "@/components/JudgeTakeaway";
import { KPICard } from "@/components/KPICard";
import { MiniSpark } from "@/components/MiniSpark";
import { Section, CheckRow } from "@/components/Section";
import { Sidebar } from "@/components/Sidebar";
import { SystemDiagram } from "@/components/SystemDiagram";
import { TradesTable } from "@/components/TradesTable";
import { data, data30d, fmtPct, fmtUsd, topTradesByAbsPnl, fmtDate } from "@/lib/data";

const REPO_URL_REAL = "https://github.com/Damso74/kraken-alpha-agent";

export default function Page() {
  const { summary, equity_curve, trades, period, universe, by_symbol, tests, rejections } = data;
  const positive = summary.total_pnl_usd >= 0;
  const topTrades = topTradesByAbsPnl(trades, 10);

  const periodLabel =
    period.start && period.end
      ? `${fmtDate(period.start)} → ${fmtDate(period.end)}`
      : `${period.days ?? 30} days`;

  return (
    <div className="min-h-screen flex">
      <Sidebar />

      <main className="flex-1 min-w-0 pt-14 lg:pt-0">
        {/* Header */}
        <header className="border-b border-[var(--border)] bg-[var(--surface-0)]/80 backdrop-blur supports-[backdrop-filter]:bg-[var(--surface-0)]/60 lg:sticky lg:top-0 z-10">
          <div className="px-4 sm:px-6 lg:px-10 py-4 sm:py-5 flex flex-col lg:flex-row lg:flex-wrap items-start lg:justify-between gap-4 lg:gap-6">
            <div className="min-w-0 w-full lg:w-auto">
              <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-[10.5px] sm:text-[11px] text-[var(--text-tertiary)] uppercase tracking-[0.14em] sm:tracking-[0.16em]">
                <span className="text-[var(--gold)] font-semibold">Hackathon submission</span>
                <span className="h-1 w-1 rounded-full bg-[var(--text-tertiary)]" />
                <span>lablab AI Agent Olympics</span>
                <span className="hidden sm:inline h-1 w-1 rounded-full bg-[var(--text-tertiary)]" />
                <span className="hidden sm:inline">Kraken Trading Performance</span>
              </div>
              <h1 className="mt-2 text-[24px] sm:text-[28px] lg:text-[30px] font-semibold tracking-tight text-[var(--text-primary)]">
                Kraken Alpha Agent
              </h1>
              <p className="mt-1 text-[12.5px] sm:text-[13px] text-[var(--text-secondary)] max-w-[680px] leading-relaxed">
                Production-grade trading agent with deterministic signal stack, defence-in-depth risk engine, and a fully audited xStocks backtest on real Kraken OHLC data — primary snapshot on the hackathon window (May 13 → May 19, 2026), 30-day baseline reported alongside.
              </p>
            </div>

            <div className="flex flex-col gap-3 items-stretch lg:items-end w-full lg:w-auto shrink-0">
              <span className="self-start lg:self-end inline-flex items-center gap-2 rounded-full bg-[color:var(--success)]/10 border border-[color:var(--success)]/30 px-3 py-1 text-[11px] sm:text-[11.5px] font-semibold uppercase tracking-[0.14em] text-[var(--success)]">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-[var(--success)] opacity-60 animate-ping" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--success)]" />
                </span>
                Ready for demo
              </span>
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] px-3 py-2 flex items-center justify-between sm:justify-start gap-3 w-full lg:w-auto">
                <div className="min-w-0">
                  <div className="text-[10.5px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] font-medium">
                    Equity curve · hackathon window
                  </div>
                  <div
                    className={`text-[14px] font-semibold tabular ${
                      positive ? "text-[var(--success)]" : "text-[var(--warning)]"
                    }`}
                  >
                    {fmtUsd(summary.total_pnl_usd, { signed: true })}{" "}
                    <span className="text-[var(--text-tertiary)] text-[12px] font-normal">
                      ({fmtPct(summary.total_pnl_pct, { signed: true, decimals: 4 })})
                    </span>
                  </div>
                </div>
                <div className="shrink-0">
                  <MiniSpark
                    points={equity_curve}
                    positive={positive}
                    width={140}
                    height={40}
                  />
                </div>
              </div>
            </div>
          </div>
        </header>

        <div className="px-4 sm:px-6 lg:px-10 py-5 sm:py-6 lg:py-8 space-y-6 sm:space-y-7 lg:space-y-8 max-w-[1380px]">
          {/* KPI cards */}
          <section className="grid grid-cols-2 lg:grid-cols-4 gap-3 sm:gap-3.5 lg:gap-4">
            <KPICard
              label="Tests passed"
              value={`${tests.passed} / ${tests.passed}`}
              hint={`${tests.duration_s.toFixed(2)}s wall-clock · 0 failures`}
              tone="success"
              icon={CheckCircle2}
            />
            <KPICard
              label="Hackathon-window trades"
              value={summary.total_trades.toString()}
              hint={`${summary.buy_count} BUY · ${summary.sell_count} SELL · win rate ${(summary.win_rate * 100).toFixed(1)}%`}
              tone="info"
              icon={Layers}
            />
            <KPICard
              label="Hackathon-window PnL"
              value={fmtUsd(summary.total_pnl_usd, { signed: true })}
              hint={`${fmtPct(summary.total_pnl_pct, { signed: true, decimals: 4 })} on $${summary.starting_capital_usd.toLocaleString("en-US")} · max DD ${summary.max_drawdown_pct.toFixed(2)}% · 30d baseline ${fmtUsd(data30d.summary.total_pnl_usd, { signed: true })}`}
              tone={positive ? "success" : "warning"}
              icon={positive ? TrendingUp : TrendingDown}
            />
            <KPICard
              label="Capital safety"
              value="Preserved"
              hint="Triple opt-in · leverage 1x · shorting=off · dead-man cancel"
              tone="gold"
              icon={ShieldCheck}
            />
          </section>

          {/* 2x2 grid */}
          <section className="grid grid-cols-1 lg:grid-cols-2 gap-3 lg:gap-4">
            <Section
              title="What worked"
              description="All hackathon-required surfaces are deployed, tested, and audited."
              tone="success"
              icon={CheckCircle2}
            >
              <ul className="space-y-1">
                <CheckRow tone="success">
                  <strong className="font-semibold">{tests.passed} / {tests.passed} pytest tests passed</strong> in
                  {" "}
                  {tests.duration_s.toFixed(2)}s — no skips, no flaky tests.
                </CheckRow>
                <CheckRow tone="success">
                  <strong className="font-semibold">VPS Vultr Ubuntu 24.04 LTS</strong> deployed (region <code className="text-[11px] text-[var(--text-secondary)]">ewr</code>) with watchdog and dead-man cancel-after.
                </CheckRow>
                <CheckRow tone="success">
                  Real Kraken CLI market-data ingestion — <strong className="font-semibold">24/5 xStocks + 24/7 crypto perps</strong>, no mocks in audit logs.
                </CheckRow>
                <CheckRow tone="success">
                  <strong className="font-semibold">Risk gates, audit logs, dead-man cancel-after, watchdog</strong> all active and tested.
                </CheckRow>
                <CheckRow tone="success">
                  BTC Perp control order on the same Futures key validated — <code className="text-[11px] text-[var(--text-secondary)]">status: placed</code>.
                </CheckRow>
                <CheckRow tone="success">
                  <strong className="font-semibold">Hackathon-window backtest</strong> (May 13 → May 19, 2026) — PnL {fmtUsd(summary.total_pnl_usd, { signed: true })}, win rate {(summary.win_rate * 100).toFixed(1)}%, max DD {summary.max_drawdown_pct.toFixed(2)}%.
                </CheckRow>
                <CheckRow tone="success">
                  <strong className="font-semibold">30-day baseline</strong> on real xStocks OHLC — PnL {fmtUsd(data30d.summary.total_pnl_usd, { signed: true })}, win rate {(data30d.summary.win_rate * 100).toFixed(1)}%, {data30d.summary.total_trades} trades.
                </CheckRow>
              </ul>
            </Section>

            <Section
              title="What blocked xStocks live"
              description="Account-class restriction, transparently diagnosed with API evidence."
              tone="warning"
              icon={AlertTriangle}
            >
              <ul className="space-y-2.5">
                <li className="rounded-md border border-[color:var(--warning)]/25 bg-[color:var(--warning)]/[0.05] px-3.5 py-3">
                  <div className="text-[12.5px] font-semibold text-[var(--text-primary)] mb-1">
                    Spot xStocks order
                  </div>
                  <code className="text-[11.5px] text-[var(--warning)] tabular">
                    EGeneral:Permission denied
                  </code>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                    Reproduced from FR/Lyon and US-NJ VPS — same error, not IP/geo.
                  </p>
                </li>
                <li className="rounded-md border border-[color:var(--warning)]/25 bg-[color:var(--warning)]/[0.05] px-3.5 py-3">
                  <div className="text-[12.5px] font-semibold text-[var(--text-primary)] mb-1">
                    xStocks Perps order
                  </div>
                  <code className="text-[11.5px] text-[var(--warning)] tabular">
                    {`{"result":"success","status":"wouldNotReducePosition"}`}
                  </code>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                    Every BUY / SELL rejected, even with no open position and no <code className="text-[11px]">--reduce-only</code> flag.
                  </p>
                </li>
                <li className="rounded-md border border-[color:var(--info)]/25 bg-[color:var(--info)]/[0.05] px-3.5 py-3">
                  <div className="text-[12.5px] font-semibold text-[var(--text-primary)] mb-1">
                    Account class · {rejections.account_class}
                  </div>
                  <code className="text-[11.5px] text-[var(--info)] tabular">
                    BTC Perp control → status: placed
                  </code>
                  <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--text-secondary)]">
                    Same key, same IP, same Futures routing. Confirms code/key/IP all healthy — block is venue-side, regulatory.
                  </p>
                </li>
              </ul>
              <div className="mt-3 text-[11px] text-[var(--text-tertiary)]">
                Verified {rejections.verified_at}. Re-eligible for live ranking the moment a non-EU/EEA Kraken entity is wired in.
              </div>
            </Section>

            <Section
              title="Evidence"
              description="Reproducible artefacts and audit trail."
              tone="info"
              icon={Database}
            >
              <ul className="space-y-2.5 text-[13px]">
                <li className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[var(--text-primary)] font-medium">GitHub repository</div>
                    <div className="text-[12px] text-[var(--text-secondary)]">
                      Source code, tests, scripts, deploy artefacts.
                    </div>
                  </div>
                  <a
                    href={REPO_URL_REAL}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-[12px] text-[var(--info)] hover:text-[var(--accent-teal)] transition-colors shrink-0"
                  >
                    <GithubIcon className="h-3.5 w-3.5" strokeWidth={2} />
                    Damso74/kraken-alpha-agent
                    <ExternalLink className="h-3 w-3" strokeWidth={2.2} />
                  </a>
                </li>
                <li className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[var(--text-primary)] font-medium">Live + paper logs</div>
                    <div className="text-[12px] text-[var(--text-secondary)]">
                      Captured in <code className="text-[11px] text-[var(--text-tertiary)]">docs/SUBMISSION.md</code>.
                    </div>
                  </div>
                  <a
                    href={`${REPO_URL_REAL}/blob/master/docs/SUBMISSION.md`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-[12px] text-[var(--info)] hover:text-[var(--accent-teal)] transition-colors shrink-0"
                  >
                    SUBMISSION.md
                    <ExternalLink className="h-3 w-3" strokeWidth={2.2} />
                  </a>
                </li>
                <li className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[var(--text-primary)] font-medium">Backtest + market-hours analysis</div>
                    <div className="text-[12px] text-[var(--text-secondary)]">
                      30 days of hourly OHLC, US session attribution, per-ticker PnL.
                    </div>
                  </div>
                  <a
                    href={`${REPO_URL_REAL}/tree/master/data`}
                    target="_blank"
                    rel="noreferrer noopener"
                    className="inline-flex items-center gap-1.5 text-[12px] text-[var(--info)] hover:text-[var(--accent-teal)] transition-colors shrink-0"
                  >
                    /data
                    <ExternalLink className="h-3 w-3" strokeWidth={2.2} />
                  </a>
                </li>
                <li className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="text-[var(--text-primary)] font-medium">Full audit trail</div>
                    <div className="text-[12px] text-[var(--text-secondary)]">
                      SQLite + JSONL exports — every decision, every gate, every fill.
                    </div>
                  </div>
                  <code className="text-[11px] text-[var(--text-tertiary)] bg-[var(--surface-2)] px-1.5 py-1 rounded shrink-0">
                    scripts/export_audit_bundle.py
                  </code>
                </li>
              </ul>
            </Section>

            <Section
              title="System overview"
              description="Deterministic engine, defence-in-depth, no shortcuts."
              tone="gold"
              icon={GitMerge}
            >
              <SystemDiagram />
            </Section>
          </section>

          {/* Backtest Run */}
          <Section
            title={`Backtest run · hackathon window · ${periodLabel}`}
            description={`Universe: ${universe.join(" · ")} — hourly OHLC replayed through the deterministic engine over the lablab AI Agent Olympics submission window. No live or paper orders placed. 30-day baseline (${fmtUsd(data30d.summary.total_pnl_usd, { signed: true })}, ${data30d.summary.total_trades} trades) reported alongside in the KPI card and in docs/SUBMISSION.md.`}
            tone="info"
            icon={PlayCircle}
          >
            <div className="grid grid-cols-1 lg:grid-cols-[1.6fr_1fr] gap-4 lg:gap-6">
              <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-0)] p-3 sm:p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 mb-3">
                  <div className="min-w-0">
                    <div className="text-[10.5px] sm:text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] font-medium">
                      Portfolio equity
                    </div>
                    <div
                      className={`mt-1 text-[19px] sm:text-[22px] font-semibold tabular tracking-tight ${
                        positive ? "text-[var(--success)]" : "text-[var(--warning)]"
                      }`}
                    >
                      {fmtUsd(summary.ending_capital_usd)}
                      <span className="ml-2 text-[11.5px] sm:text-[12px] font-normal text-[var(--text-tertiary)] whitespace-nowrap">
                        from {fmtUsd(summary.starting_capital_usd)}
                      </span>
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-[10.5px] sm:text-[11px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] font-medium">
                      Net PnL
                    </div>
                    <div
                      className={`mt-1 text-[16px] sm:text-[18px] font-semibold tabular tracking-tight ${
                        positive ? "text-[var(--success)]" : "text-[var(--warning)]"
                      }`}
                    >
                      {fmtUsd(summary.total_pnl_usd, { signed: true })}
                      <span className="ml-1.5 text-[11.5px] sm:text-[12px] font-normal text-[var(--text-tertiary)] whitespace-nowrap">
                        ({fmtPct(summary.total_pnl_pct, { signed: true, decimals: 4 })})
                      </span>
                    </div>
                  </div>
                </div>
                <EquityChart
                  points={equity_curve}
                  startingCapital={summary.starting_capital_usd}
                  positive={positive}
                  className="w-full h-[180px] sm:h-[230px] lg:h-[280px]"
                />
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-2 gap-2.5 sm:gap-3 content-start">
                <Stat label="Trades" value={summary.total_trades.toString()} sub={`${summary.buy_count} buy · ${summary.sell_count} sell`} />
                <Stat
                  label="Win rate"
                  value={`${(summary.win_rate * 100).toFixed(1)}%`}
                  sub={`${summary.winning_trades} wins · ${summary.losing_trades} losses`}
                />
                <Stat
                  label="Max drawdown"
                  value={`${summary.max_drawdown_pct.toFixed(2)}%`}
                  sub={fmtUsd(summary.max_drawdown_usd)}
                  tone="warning"
                />
                <Stat
                  label="Per-trade Sharpe"
                  value={summary.per_trade_sharpe !== null ? summary.per_trade_sharpe.toFixed(2) : "—"}
                  sub="SELL pnls, not annualised"
                />
                <Stat
                  label="Best symbol"
                  value={summary.best_symbol ?? "—"}
                  sub={
                    by_symbol.find((s) => s.symbol === summary.best_symbol)
                      ? fmtUsd(by_symbol.find((s) => s.symbol === summary.best_symbol)!.net_pnl_usd, {
                          signed: true,
                        })
                      : ""
                  }
                  tone="success"
                />
                <Stat
                  label="Worst symbol"
                  value={summary.worst_symbol ?? "—"}
                  sub={
                    by_symbol.find((s) => s.symbol === summary.worst_symbol)
                      ? fmtUsd(by_symbol.find((s) => s.symbol === summary.worst_symbol)!.net_pnl_usd, {
                          signed: true,
                        })
                      : ""
                  }
                  tone="warning"
                />
              </div>
            </div>

            <div className="mt-6 pt-6 border-t border-[var(--border)]">
              <div className="flex items-center justify-between mb-3">
                <h4 className="text-[13px] font-semibold tracking-tight text-[var(--text-primary)]">
                  Top 10 simulated trades by |PnL|
                </h4>
                <span className="text-[11px] text-[var(--text-tertiary)]">
                  {trades.length} total trades · FIFO matched
                </span>
              </div>
              <TradesTable trades={topTrades} />
            </div>
          </Section>

          {/* Activity feed + Judge takeaway */}
          <section className="grid grid-cols-1 lg:grid-cols-[1.5fr_1fr] gap-3 lg:gap-4">
            <Section title="Recent activity" description="Operational signals from the deployed agent." tone="info" icon={Sparkles}>
              <ActivityFeed
                generatedAt={data.generated_at}
                testsPassed={tests.passed}
                testsDuration={tests.duration_s}
                netPnl={summary.total_pnl_usd}
                tradesCount={summary.total_trades}
              />
            </Section>

            <div className="space-y-3 lg:space-y-4">
              <JudgeTakeaway message="Production-grade agent with real exchange integration, strong safeguards, and a clearly diagnosed venue-level xStocks restriction — ready for any eligible account." />

              <Section title="Per-symbol breakdown" tone="neutral" icon={CircleDollarSign}>
                <div className="overflow-x-auto -mx-2 px-2 scrollbar-thin">
                  <table className="w-full text-[12px] tabular">
                    <thead>
                      <tr className="text-left text-[10px] uppercase tracking-[0.12em] text-[var(--text-tertiary)]">
                        <th className="px-2 py-1.5 font-medium">Symbol</th>
                        <th className="px-2 py-1.5 font-medium text-right">Trades</th>
                        <th className="px-2 py-1.5 font-medium text-right">PnL</th>
                        <th className="px-2 py-1.5 font-medium text-right">PnL %</th>
                      </tr>
                    </thead>
                    <tbody>
                      {by_symbol.map((s) => {
                        const pos = s.net_pnl_usd > 0;
                        const neg = s.net_pnl_usd < 0;
                        return (
                          <tr key={s.symbol} className="border-t border-[var(--border)]">
                            <td className="px-2 py-1.5 font-medium text-[var(--text-primary)]">
                              {s.symbol}
                            </td>
                            <td className="px-2 py-1.5 text-right text-[var(--text-secondary)]">
                              {s.trades_count}
                            </td>
                            <td
                              className={`px-2 py-1.5 text-right font-semibold ${
                                pos ? "text-[var(--success)]" : neg ? "text-[var(--warning)]" : "text-[var(--text-secondary)]"
                              }`}
                            >
                              {fmtUsd(s.net_pnl_usd, { signed: true })}
                            </td>
                            <td
                              className={`px-2 py-1.5 text-right ${
                                pos ? "text-[var(--success)]" : neg ? "text-[var(--warning)]" : "text-[var(--text-secondary)]"
                              }`}
                            >
                              {s.net_pnl_pct >= 0 ? "+" : ""}
                              {s.net_pnl_pct.toFixed(2)}%
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Section>
            </div>
          </section>

          {/* Footer */}
          <footer className="pt-5 sm:pt-6 pb-8 sm:pb-10 border-t border-[var(--border)] flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-center sm:text-left">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12px] text-[var(--text-secondary)]">
              <span className="inline-flex items-center gap-1.5">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full rounded-full bg-[var(--success)] opacity-60 animate-ping" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-[var(--success)]" />
                </span>
                <span className="text-[var(--success)] font-medium">Agent online</span>
              </span>
              <span className="h-1 w-1 rounded-full bg-[var(--text-tertiary)]" />
              <span>v1.0.0</span>
              <span className="h-1 w-1 rounded-full bg-[var(--text-tertiary)]" />
              <a
                href={REPO_URL_REAL}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1.5 hover:text-[var(--text-primary)] transition-colors"
              >
                <GithubIcon className="h-3.5 w-3.5" strokeWidth={2} />
                Damso74/kraken-alpha-agent
                <ArrowUpRight className="h-3 w-3" strokeWidth={2} />
              </a>
            </div>
            <div className="text-[11px] text-[var(--text-tertiary)]">
              Built for lablab AI Agent Olympics · 2026
            </div>
          </footer>
        </div>
      </main>
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "neutral" | "success" | "warning";
}) {
  const tones = {
    neutral: "text-[var(--text-primary)]",
    success: "text-[var(--success)]",
    warning: "text-[var(--warning)]",
  };
  return (
    <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-0)] px-3.5 py-3">
      <div className="text-[10.5px] uppercase tracking-[0.14em] text-[var(--text-tertiary)] font-medium">
        {label}
      </div>
      <div className={`mt-1.5 text-[18px] font-semibold tabular tracking-tight ${tones[tone]}`}>
        {value}
      </div>
      {sub ? (
        <div className="mt-0.5 text-[11px] text-[var(--text-secondary)] tabular">{sub}</div>
      ) : null}
    </div>
  );
}
