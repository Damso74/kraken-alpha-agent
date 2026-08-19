"""Export the latest 30-day xStocks backtest into the web submission JSON.

Reads ``data/backtest_latest.json`` (produced by
``scripts/backtest_xstocks.py``) and re-serialises it into
``web/public/data/backtest_xstocks_30d.json`` with a flat, UI-friendly
schema consumed by the Next.js submission page.

This script is read-only with respect to the simulator output: every
number it emits comes from the canonical backtest payload, with two
exceptions that are clearly labelled in the JSON:

- ``rejections``  — static block describing the PEDSL-CY venue
  restriction (mirrored from ``AGENTS.md``); not a backtest metric.
- ``tests``       — populated from ``--tests-passed/--tests-failed``
  CLI args (defaulting to 232/0/2.47s, the snapshot at HEAD 72a1fa7);
  not a backtest metric either.

No live or paper orders are placed. No config files are mutated.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Convert data/backtest_latest.json into "
            "web/public/data/backtest_xstocks_30d.json"
        )
    )
    p.add_argument(
        "--input",
        type=str,
        default="data/backtest_latest.json",
        help="path to the canonical backtest JSON (default data/backtest_latest.json)",
    )
    p.add_argument(
        "--output",
        type=str,
        default="web/public/data/backtest_xstocks_30d.json",
        help="path to write the web-friendly JSON",
    )
    p.add_argument(
        "--starting-capital",
        type=float,
        default=None,
        help="override the starting USD capital (defaults to backtest initial_cash)",
    )
    p.add_argument("--tests-passed", type=int, default=232, help="pytest passed count")
    p.add_argument("--tests-failed", type=int, default=0, help="pytest failed count")
    p.add_argument(
        "--tests-duration",
        type=float,
        default=2.47,
        help="pytest duration in seconds",
    )
    p.add_argument(
        "--note",
        action="append",
        default=None,
        help=(
            "extra note string to prepend to summary.notes. Can be passed "
            "multiple times to add several notes."
        ),
    )
    p.add_argument(
        "--snapshot-label",
        type=str,
        default=None,
        help=(
            "optional label exposed under summary.snapshot_label "
            "(e.g. 'micro_15m', 'standard_30d', 'long_term'). "
            "Purely informational; does not change any metric."
        ),
    )
    return p.parse_args()


def _parse_iso(ts: str) -> datetime:
    s = ts.strip().replace("Z", "+00:00")
    return datetime.fromisoformat(s)


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _build_equity_curve(
    by_symbol: dict[str, dict[str, Any]],
    *,
    initial_cash: float,
) -> list[dict[str, Any]]:
    """Aggregate per-symbol cash_after over time into a portfolio equity curve.

    Strategy: every symbol gets a fixed slice of ``initial_cash`` at t0.
    We collect every (timestamp, symbol, cash_after) event, sort by
    timestamp, and at each event replace that symbol's last-known cash
    in a rolling map. The equity at that step is the sum of all symbol
    cash slices (initial slice for untouched symbols, latest cash_after
    otherwise). This is a deliberate simplification: the simulator's
    per-candle unrealised mark-to-market isn't surfaced in the canonical
    payload, so we step-function on realised events only.
    """
    if not by_symbol:
        return []

    n = len(by_symbol)
    per_slice = initial_cash / n if n > 0 else 0.0
    cash_now: dict[str, float] = {sym: per_slice for sym in by_symbol}

    events: list[tuple[datetime, str, float]] = []
    earliest: datetime | None = None

    for sym, res in by_symbol.items():
        for trade in res.get("trades") or []:
            ts_raw = trade.get("timestamp_utc")
            cash_after = trade.get("cash_after")
            if not ts_raw or cash_after is None:
                continue
            try:
                ts = _parse_iso(ts_raw)
            except ValueError:
                continue
            events.append((ts, sym, float(cash_after)))
            if earliest is None or ts < earliest:
                earliest = ts

    events.sort(key=lambda e: e[0])

    curve: list[dict[str, Any]] = []
    if earliest is not None:
        curve.append({"ts": _iso(earliest), "equity_usd": round(initial_cash, 4)})

    for ts, sym, cash_after in events:
        cash_now[sym] = cash_after
        equity = sum(cash_now.values())
        curve.append({"ts": _iso(ts), "equity_usd": round(equity, 4)})

    return curve


def _pair_trades(by_symbol: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """FIFO-match BUY → SELL trades inside each symbol and emit pair rows."""
    paired: list[dict[str, Any]] = []
    for sym, res in by_symbol.items():
        open_buys: list[dict[str, Any]] = []
        for trade in res.get("trades") or []:
            side = (trade.get("side") or "").upper()
            if side == "BUY":
                open_buys.append(dict(trade))
                continue
            if side != "SELL":
                continue
            if not open_buys:
                continue
            entry = open_buys.pop(0)
            try:
                ts_in = _parse_iso(entry["timestamp_utc"])
                ts_out = _parse_iso(trade["timestamp_utc"])
                duration_min = max(0, int((ts_out - ts_in).total_seconds() // 60))
            except (KeyError, ValueError):
                duration_min = None

            qty = float(entry.get("qty") or 0.0)
            entry_price = float(entry.get("price") or 0.0)
            exit_price = float(trade.get("price") or 0.0)
            size_usd = qty * entry_price
            pnl_usd = float(trade.get("pnl") or 0.0)
            paired.append(
                {
                    "ts": entry.get("timestamp_utc"),
                    "exit_ts": trade.get("timestamp_utc"),
                    "symbol": sym,
                    "action": "BUY",
                    "size_usd": round(size_usd, 4),
                    "qty": round(qty, 8),
                    "fill_price": round(entry_price, 6),
                    "exit_price": round(exit_price, 6),
                    "exit_reason": trade.get("reason") or "exit",
                    "pnl_usd": round(pnl_usd, 4),
                    "pnl_pct": round(
                        (pnl_usd / size_usd * 100.0) if size_usd > 0 else 0.0, 4
                    ),
                    "duration_min": duration_min,
                }
            )
    paired.sort(key=lambda t: (t.get("ts") or ""))
    return paired


def _period_from_curve(curve: list[dict[str, Any]]) -> dict[str, Any]:
    if not curve:
        return {"start": None, "end": None, "days": 0}
    try:
        start = _parse_iso(curve[0]["ts"])
        end = _parse_iso(curve[-1]["ts"])
        days = max(1, int(math.ceil((end - start).total_seconds() / 86400.0)))
    except (KeyError, ValueError):
        return {"start": None, "end": None, "days": 0}
    return {
        "start": start.date().isoformat(),
        "end": end.date().isoformat(),
        "days": days,
    }


def _build_payload(
    *,
    src: dict[str, Any],
    starting_capital: float | None,
    tests_passed: int,
    tests_failed: int,
    tests_duration: float,
    extra_notes: list[str] | None = None,
    snapshot_label: str | None = None,
) -> dict[str, Any]:
    portfolio = src.get("portfolio") or {}
    by_symbol = portfolio.get("by_symbol") or {}
    universe = list(src.get("symbols") or list(by_symbol.keys()))

    initial_cash = float(starting_capital or portfolio.get("initial_cash") or 10_000.0)
    final_cash = float(portfolio.get("equity_final") or portfolio.get("final_cash") or initial_cash)
    net_pnl = float(portfolio.get("net_pnl") or 0.0)
    net_pnl_pct = float(portfolio.get("net_pnl_pct") or 0.0)
    max_dd_pct = float(portfolio.get("max_drawdown_pct") or 0.0)
    win_rate = float(portfolio.get("win_rate") or 0.0)
    trades_count = int(portfolio.get("trades_count") or 0)
    wins = int(portfolio.get("wins") or 0)
    losses = int(portfolio.get("losses") or 0)
    buys = int(portfolio.get("buy_count") or 0)
    sells = int(portfolio.get("sell_count") or 0)

    # Sharpe approximation: use per-trade PnL series. The canonical
    # backtest payload doesn't expose returns timestamps fine enough
    # for an annualised Sharpe; we report a per-trade Sharpe-like
    # statistic and label it accordingly.
    pnls: list[float] = []
    for res in by_symbol.values():
        for t in res.get("trades") or []:
            if (t.get("side") or "").upper() == "SELL":
                pnls.append(float(t.get("pnl") or 0.0))
    if len(pnls) >= 2:
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        per_trade_sharpe = round(mean / std, 4) if std > 0 else None
    else:
        per_trade_sharpe = None

    equity_curve = _build_equity_curve(by_symbol, initial_cash=initial_cash)
    paired_trades = _pair_trades(by_symbol)
    period = _period_from_curve(equity_curve)

    # The period above is computed from realised trade timestamps only
    # (i.e. the first BUY → last SELL window). The actual OHLC window
    # is wider: ``candles_per_symbol`` × ``interval_minutes``. We expose
    # the wider window so the "30 days" framing matches the OHLC depth.
    candles_per_symbol = src.get("candles_per_symbol") or {}
    interval_minutes = int(src.get("interval_minutes") or 60)
    median_candles_per_symbol: int | None = None
    if candles_per_symbol:
        max_candles = max(int(v) for v in candles_per_symbol.values())
        ohlc_days = max(1, int(round(max_candles * interval_minutes / 60.0 / 24.0)))
        period["ohlc_days"] = ohlc_days
        period["active_days"] = period.get("days") or 0
        period["days"] = ohlc_days
        sorted_counts = sorted(int(v) for v in candles_per_symbol.values())
        mid = len(sorted_counts) // 2
        median_candles_per_symbol = (
            sorted_counts[mid]
            if len(sorted_counts) % 2 == 1
            else (sorted_counts[mid - 1] + sorted_counts[mid]) // 2
        )

    by_symbol_summary = []
    for sym in universe:
        res = by_symbol.get(sym) or {}
        by_symbol_summary.append(
            {
                "symbol": sym,
                "trades_count": int(res.get("trades_count") or 0),
                "buy_count": int(res.get("buy_count") or 0),
                "sell_count": int(res.get("sell_count") or 0),
                "wins": int(res.get("wins") or 0),
                "losses": int(res.get("losses") or 0),
                "net_pnl_usd": round(float(res.get("net_pnl") or 0.0), 4),
                "net_pnl_pct": round(float(res.get("net_pnl_pct") or 0.0), 4),
                "max_drawdown_pct": round(float(res.get("max_drawdown_pct") or 0.0), 4),
                "last_price": round(float(res.get("last_price") or 0.0), 6),
            }
        )

    payload: dict[str, Any] = {
        "generated_at": src.get("generated_at"),
        "profile": src.get("profile"),
        "source": "backtest_local_estimate",
        "engine": "dry_run",
        "interval_minutes": int(src.get("interval_minutes") or 60),
        "period": period,
        "universe": universe,
        "summary": {
            "starting_capital_usd": round(initial_cash, 4),
            "ending_capital_usd": round(final_cash, 4),
            "total_pnl_usd": round(net_pnl, 4),
            "total_pnl_pct": round(net_pnl_pct, 4),
            "max_drawdown_usd": round(initial_cash * max_dd_pct / 100.0 * -1.0, 4),
            "max_drawdown_pct": round(max_dd_pct, 4),
            "total_trades": trades_count,
            "buy_count": buys,
            "sell_count": sells,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(win_rate, 4),
            "per_trade_sharpe": per_trade_sharpe,
            "best_symbol": portfolio.get("best_symbol"),
            "worst_symbol": portfolio.get("worst_symbol"),
            "interval_minutes": interval_minutes,
            "candles_per_symbol": median_candles_per_symbol,
            "candles_total": (
                sum(int(v) for v in candles_per_symbol.values())
                if candles_per_symbol
                else None
            ),
        },
        "by_symbol": by_symbol_summary,
        "equity_curve": equity_curve,
        "trades": paired_trades,
        "rejection_reasons_top": list(portfolio.get("risk_reasons_top") or [])[:6],
        "rejections": {
            "live_xstocks_spot": "EGeneral:Permission denied (PEDSL-CY)",
            "live_xstocks_perps": (
                "wouldNotReducePosition (every BUY/SELL rejected, "
                "even without --reduce-only)"
            ),
            "btc_perp_control": "status:placed (proves API/key/futures routing OK)",
            "account_class": "PEDSL-CY (Cyprus EU)",
            "verified_at": "2026-05-15",
        },
        "tests": {
            "passed": int(tests_passed),
            "failed": int(tests_failed),
            "duration_s": float(tests_duration),
        },
        "notes": _build_notes(src=src, interval_minutes=interval_minutes),
    }
    if extra_notes:
        payload["notes"] = list(extra_notes) + payload["notes"]
    if snapshot_label:
        payload["summary"]["snapshot_label"] = snapshot_label
    return payload


def _build_notes(*, src: dict[str, Any], interval_minutes: int) -> list[str]:
    notes: list[str] = [
        "Equity curve is a step function over realised events. "
        "Per-candle mark-to-market is not surfaced in the canonical payload.",
        "Per-trade Sharpe is computed on SELL pnls; not annualised.",
        "Trade pairs are FIFO-matched BUY → SELL inside each symbol.",
        f"Replayed at {interval_minutes}-minute candle resolution.",
    ]
    # ``build_run_payload`` flattens extras into the payload root rather
    # than nesting them under an ``extras`` key, so look in both spots.
    extras_raw = src.get("extras") or {}
    extras = {
        "include_low_liquidity": extras_raw.get("include_low_liquidity")
        if extras_raw.get("include_low_liquidity") is not None
        else src.get("include_low_liquidity"),
        "disable_realtime_cooldown": extras_raw.get("disable_realtime_cooldown")
        if extras_raw.get("disable_realtime_cooldown") is not None
        else src.get("disable_realtime_cooldown"),
    }
    if extras.get("include_low_liquidity"):
        notes.append(
            "Backtest analysis variant: LOW_LIQUIDITY gate relaxed to expose "
            "the full deterministic-engine surface. Live and paper engines "
            "keep the gate enabled (see AGENTS.md / src/risk.py)."
        )
    if extras.get("disable_realtime_cooldown"):
        notes.append(
            "Backtest analysis variant: per-symbol cooldown disabled "
            "(cooldown_seconds_per_symbol = 0). The risk layer's cooldown "
            "uses time.time() (wall clock), which does not advance during "
            "candle replay; the override lets the strategy re-enter on "
            "successive signals over the full window. Live and paper "
            "engines keep the cooldown gate enabled."
        )
    return notes


def main() -> int:
    args = _parse_args()
    in_path = (ROOT / args.input).resolve()
    out_path = (ROOT / args.output).resolve()

    if not in_path.exists():
        print(f"ERROR: input file not found: {in_path}", file=sys.stderr)
        return 2

    src = json.loads(in_path.read_text(encoding="utf-8"))
    payload = _build_payload(
        src=src,
        starting_capital=args.starting_capital,
        tests_passed=args.tests_passed,
        tests_failed=args.tests_failed,
        tests_duration=args.tests_duration,
        extra_notes=args.note,
        snapshot_label=args.snapshot_label,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    summary = payload["summary"]
    print(
        f"Exported {payload['period'].get('days', 0)}d backtest -> {out_path}\n"
        f"  trades={summary['total_trades']} "
        f"(BUY={summary['buy_count']}, SELL={summary['sell_count']}) | "
        f"wins/losses={summary['winning_trades']}/{summary['losing_trades']} | "
        f"win_rate={summary['win_rate']:.2%} | "
        f"net_pnl={summary['total_pnl_usd']:+.2f} USD "
        f"({summary['total_pnl_pct']:+.4f}%) | "
        f"mdd={summary['max_drawdown_pct']:.2f}%"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
