"""Historical replay backtester for the xStocks universe.

Strictly read-only: pulls OHLC candles through the existing
``KrakenCLI`` wrapper (which injects ``--asset-class tokenized_asset`` for
xStocks) and simulates fills locally. The script never invokes
``kraken paper`` / ``kraken order`` and never imports ``src.execution``.

Outputs (all labelled ``backtest_local_estimate``):
- ``data/backtest_<timestamp>.json``
- ``data/backtest_<timestamp>.csv``  (simulated trades table)
- ``data/backtest_latest.json``      (copy of the latest run)
- ``data/backtest_latest.csv``       (copy of the latest run)
- ``data/backtest_report_<timestamp>.md``
- ``data/backtest_report_latest.md``

Usage examples (PowerShell)::

    python scripts/backtest_xstocks.py --symbols NVDAx MSTRx CRCLx
    python scripts/backtest_xstocks.py --top 8 --grid-search
    python scripts/backtest_xstocks.py --top 5 --include-low-liquidity
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Sequence

# Allow running from anywhere: ``python scripts/backtest_xstocks.py``
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import backtest  # noqa: E402
from src import market_data  # noqa: E402
from src.backtest import SOURCE_LABEL  # noqa: E402
from src.config import get_settings, reload_settings  # noqa: E402
from src.kraken_ohlc_paginated import (  # noqa: E402
    KRAKEN_OHLC_CAP_PER_CALL,
    OHLCFetchError,
    fetch_ohlc_paginated,
)
from src.logger import get_logger  # noqa: E402
from src.universe import get_universe_tickers, pair_format  # noqa: E402
from src.utils import utc_now_iso  # noqa: E402

logger = get_logger("backtest_xstocks")

# Calibration grid required by the project plan. Kept here (and not in the
# library module) so the script stays the single source of truth for the
# competition session's hyper-parameter sweep.
DEFAULT_GRID: dict[str, list[Any]] = {
    "min_opportunity_score_buy": [0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.18],
    "min_opportunity_score_sell": [0.06, 0.08, 0.10, 0.12],
    "max_spread_bps": [80, 100, 120, 150],
    "top_n": [3, 5, 8],
    "block_low_liquidity": [True, False],
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Replay historical OHLC candles through the deterministic engine "
            "and simulate fills locally. Read-only — no paper, no live."
        )
    )
    p.add_argument(
        "--symbols",
        nargs="+",
        default=None,
        help="explicit symbol list (e.g. NVDAx MSTRx CRCLx). Falls back to --top.",
    )
    p.add_argument("--top", type=int, default=8, help="top-N symbols from latest ranking when --symbols is absent")
    p.add_argument("--profile", type=str, default=None, help="override active profile for this run")
    p.add_argument("--interval", type=int, default=60, help="candle interval in minutes (default 60)")
    p.add_argument("--initial-cash", type=float, default=10_000.0, help="starting USD capital")
    p.add_argument("--hours", type=int, default=None, help="optional cap on candle depth (last N hours)")
    p.add_argument(
        "--target-candles",
        type=int,
        default=None,
        help=(
            "optional explicit target number of candles per symbol. When > 720 "
            "(Kraken's per-call cap), the backtest uses the paginated OHLC "
            "fetcher (src.kraken_ohlc_paginated) which advances --since "
            "between calls. Note that Kraken does not expose history older "
            "than ~720 candles per interval, so requesting more than the "
            "natural depth simply yields the natural depth."
        ),
    )
    p.add_argument(
        "--include-low-liquidity",
        action="store_true",
        help=(
            "override block_low_liquidity = False in the simulation only. "
            "Never touches config.yaml."
        ),
    )
    p.add_argument(
        "--disable-realtime-cooldown",
        action="store_true",
        help=(
            "force cooldown_seconds_per_symbol = 0 inside the simulator. "
            "The risk layer's cooldown gate uses time.time() (wall clock) "
            "which does not advance with replayed candles, so a single BUY "
            "would otherwise block every subsequent BUY on the same symbol "
            "for the rest of the run. Simulation-only; live and paper paths "
            "are unaffected (config.yaml is never mutated)."
        ),
    )
    p.add_argument("--grid-search", action="store_true", help="evaluate the calibration grid")
    p.add_argument(
        "--market-hours-report",
        action="store_true",
        help=(
            "after the standard run, classify candles by US session "
            "(America/New_York) and compare two simulation variants: "
            "A=block_low_liquidity (live/paper safety), "
            "B=allow_low_liquidity (backtest analysis only). "
            "Writes data/market_hours_report_<ts>.json and .md."
        ),
    )
    p.add_argument(
        "--max-combos",
        type=int,
        default=None,
        help="cap on the number of grid combos (defaults to the full grid).",
    )
    p.add_argument(
        "--grid-candles",
        type=int,
        default=96,
        help=(
            "tail-only candle cap for grid search (default 96 = 4 days of\n            hourly data). Set to 0 to disable the cap."
        ),
    )
    p.add_argument(
        "--output-prefix",
        type=str,
        default="data/backtest",
        help="output prefix relative to project root (default data/backtest)",
    )
    return p.parse_args()


def _resolve_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [s.strip() for s in args.symbols if s and s.strip()]
    top_n = max(1, int(args.top or 1))
    data_dir = ROOT / "data"
    latest = data_dir / "xstocks_rank_latest.json"
    if latest.exists():
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            rows = payload.get("rows") or []
            ranked: list[str] = []
            for row in rows:
                sym = row.get("symbol") if isinstance(row, dict) else None
                if sym and (row.get("skipped_reason") is None):
                    ranked.append(sym)
                if len(ranked) >= top_n:
                    break
            if ranked:
                return ranked
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read xstocks_rank_latest.json: %s", exc)
    # Fallback to allowlist if ranking missing.
    return get_universe_tickers()[:top_n]


def _fetch_ohlc_for_symbols(
    symbols: Sequence[str],
    *,
    interval_minutes: int,
    hours: int | None,
    target_candles: int | None = None,
) -> tuple[dict[str, list[dict[str, float]]], dict[str, int]]:
    """Fetch OHLC candles per symbol.

    When ``target_candles`` is set and exceeds Kraken's per-call cap
    (:data:`KRAKEN_OHLC_CAP_PER_CALL` = 720), we route through
    :func:`src.kraken_ohlc_paginated.fetch_ohlc_paginated` which advances
    ``--since`` across multiple calls. Otherwise we keep the original
    single-call path through :mod:`src.market_data`.
    """
    quote = get_settings().config.universe.quote
    out: dict[str, list[dict[str, float]]] = {}
    counts: dict[str, int] = {}
    # Default to a generous count so we get the full depth Kraken returns.
    cap_from_hours = (
        max(24, int((hours * 60) // max(1, interval_minutes))) if hours else 720
    )
    cap = max(cap_from_hours, int(target_candles or 0)) if target_candles else cap_from_hours

    use_pagination = bool(target_candles and target_candles > KRAKEN_OHLC_CAP_PER_CALL)

    for sym in symbols:
        rows: list[dict[str, float]] = []
        if use_pagination:
            try:
                paginated_rows = fetch_ohlc_paginated(
                    pair_format(sym, quote),
                    interval_min=interval_minutes,
                    target_candles=int(target_candles),
                    asset_class="tokenized_asset",
                )
                rows = [r.as_market_data_dict() for r in paginated_rows]
            except OHLCFetchError as exc:
                logger.warning(
                    "paginated OHLC failed for %s, falling back to single-call: %s",
                    sym, exc,
                )
                rows = market_data.get_ohlc(
                    sym, quote, interval_minutes=interval_minutes,
                    count=KRAKEN_OHLC_CAP_PER_CALL,
                )
        else:
            rows = market_data.get_ohlc(
                sym, quote, interval_minutes=interval_minutes, count=cap
            )
        if not isinstance(rows, list):
            rows = []
        if hours:
            rows = rows[-cap_from_hours:]
        out[sym] = rows
        counts[sym] = len(rows)
        logger.info(
            "ohlc %s: %d candles (interval=%dm, paginated=%s)",
            sym, len(rows), interval_minutes, use_pagination,
        )
    return out, counts


def _write_outputs(
    *,
    payload: dict[str, Any],
    trades: list[dict[str, Any]],
    output_prefix: str,
    timestamp: str,
) -> dict[str, Path]:
    out_dir = (ROOT / output_prefix).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(output_prefix).name

    json_path = out_dir / f"{stem}_{timestamp}.json"
    csv_path = out_dir / f"{stem}_{timestamp}.csv"
    json_latest = out_dir / f"{stem}_latest.json"
    csv_latest = out_dir / f"{stem}_latest.csv"

    json_text = json.dumps(payload, indent=2, default=str)
    json_path.write_text(json_text, encoding="utf-8")
    json_latest.write_text(json_text, encoding="utf-8")

    fields = [
        "timestamp_utc",
        "symbol",
        "side",
        "price",
        "qty",
        "pnl",
        "reason",
        "cash_after",
        "equity_after",
        "source",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for trade in trades:
            writer.writerow({k: trade.get(k, "") for k in fields})
    # Mirror the same CSV to latest.
    csv_latest.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

    return {
        "json": json_path,
        "csv": csv_path,
        "json_latest": json_latest,
        "csv_latest": csv_latest,
    }


def _format_pct(value: float | int) -> str:
    return f"{value:+.2f}%"


def _format_money(value: float | int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.2f}"


def _markdown_report(payload: dict[str, Any]) -> str:
    portfolio = payload.get("portfolio") or {}
    grid = payload.get("grid")
    symbols = payload.get("symbols") or []
    candles_map = payload.get("candles_per_symbol") or {}
    by_symbol = portfolio.get("by_symbol") or {}

    lines: list[str] = []
    lines.append("# Backtest report — Kraken Alpha Agent\n")
    lines.append(f"- Timestamp UTC : `{payload.get('generated_at')}`")
    lines.append(f"- Profil : `{payload.get('profile')}`")
    lines.append(f"- Symboles : `{', '.join(symbols) or '-'}`")
    lines.append(f"- Intervalle (minutes) : `{payload.get('interval_minutes')}`")
    lines.append(f"- Source : `{payload.get('source')}`")

    lines.append("\n## Candles par symbole\n")
    lines.append("| Symbole | Candles |")
    lines.append("|---------|---------|")
    for sym in symbols:
        lines.append(f"| {sym} | {candles_map.get(sym, 0)} |")

    lines.append("\n## Portfolio (agrégé)\n")
    lines.append(f"- Cash initial : {_format_money(portfolio.get('initial_cash', 0))}")
    lines.append(f"- Equity finale : {_format_money(portfolio.get('equity_final', 0))}")
    lines.append(f"- realized_pnl : {_format_money(portfolio.get('realized_pnl', 0))}")
    lines.append(f"- unrealized_pnl : {_format_money(portfolio.get('unrealized_pnl', 0))}")
    lines.append(f"- net_pnl : {_format_money(portfolio.get('net_pnl', 0))}")
    lines.append(f"- net_pnl_pct : {_format_pct(portfolio.get('net_pnl_pct', 0))}")
    lines.append(f"- max_drawdown_pct : {portfolio.get('max_drawdown_pct', 0):.2f}%")
    lines.append(f"- trades_count : {portfolio.get('trades_count', 0)}")
    lines.append(f"- win_rate : {portfolio.get('win_rate', 0):.2%}")
    lines.append(
        f"- buy_count / sell_count / hold_count : "
        f"{portfolio.get('buy_count', 0)} / "
        f"{portfolio.get('sell_count', 0)} / "
        f"{portfolio.get('hold_count', 0)}"
    )
    lines.append(f"- Meilleur symbole (net_pnl_pct) : `{portfolio.get('best_symbol') or '-'}`")
    lines.append(f"- Pire symbole : `{portfolio.get('worst_symbol') or '-'}`")

    lines.append("\n### Top 5 raisons de rejet (risk)")
    risk_top = portfolio.get("risk_reasons_top") or []
    if risk_top:
        for item in risk_top[:5]:
            lines.append(f"- `{item.get('reason')}` × {item.get('count')}")
    else:
        lines.append("- (aucune rejet enregistré)")

    lines.append("\n### Top 5 raisons actionability")
    act_top = portfolio.get("actionability_reasons_top") or []
    if act_top:
        for item in act_top[:5]:
            lines.append(f"- `{item.get('reason')}` × {item.get('count')}")
    else:
        lines.append("- (aucune raison agrégée)")

    lines.append("\n### Top 10 trades simulés")
    lines.append("| Timestamp | Symbol | Side | Price | Qty | PnL | Reason |")
    lines.append("|-----------|--------|------|-------|-----|-----|--------|")
    all_trades: list[dict[str, Any]] = []
    for sym, res in by_symbol.items():
        for trade in res.get("trades", []) or []:
            entry = dict(trade)
            entry["symbol"] = entry.get("symbol") or sym
            all_trades.append(entry)
    all_trades.sort(key=lambda t: abs(float(t.get("pnl") or 0)), reverse=True)
    if all_trades:
        for trade in all_trades[:10]:
            lines.append(
                f"| {trade.get('timestamp_utc')} | {trade.get('symbol')} | "
                f"{trade.get('side')} | {float(trade.get('price', 0)):.4f} | "
                f"{float(trade.get('qty', 0)):.6f} | "
                f"{float(trade.get('pnl', 0)):+.2f} | "
                f"{trade.get('reason') or '-'} |"
            )
    else:
        lines.append("| - | - | - | - | - | - | (aucun trade simulé) |")

    lines.append("\n## Détails par symbole")
    for sym in symbols:
        res = by_symbol.get(sym)
        if not res:
            continue
        lines.append(f"\n### {sym}")
        lines.append(f"- candles : {res.get('candles_used')}")
        lines.append(f"- net_pnl : {_format_money(res.get('net_pnl', 0))}")
        lines.append(f"- net_pnl_pct : {_format_pct(res.get('net_pnl_pct', 0))}")
        lines.append(f"- max_drawdown_pct : {res.get('max_drawdown_pct', 0):.2f}%")
        lines.append(
            f"- trades : {res.get('trades_count', 0)} "
            f"(buy={res.get('buy_count', 0)}, sell={res.get('sell_count', 0)}, "
            f"hold={res.get('hold_count', 0)})"
        )
        lines.append(f"- status : `{res.get('status')}` — {res.get('note') or '-'}")

    lines.append("\n## Recommandations de seuils")
    if grid:
        recommendations = grid.get("cautious_recommendation")
        best_adj = grid.get("best_by_adjusted_score")
        best_pnl = grid.get("best_by_net_pnl_pct")
        lines.append(
            f"- Combos testés : {grid.get('combos_evaluated')} "
            f"(durée {grid.get('duration_seconds', 0):.2f}s)"
        )
        lines.append("\n### Top 10 configs (adjusted_score = net_pnl_pct − 0.5 × max_drawdown_pct)")
        lines.append(
            "| Rang | min_buy | min_sell | max_spread | top_n | block_low_liq | "
            "adjusted | net_pnl% | mdd% | trades |"
        )
        lines.append("|------|---------|----------|------------|-------|---------------|----------|----------|------|--------|")
        for rank, combo in enumerate(grid.get("top_by_adjusted_score") or [], start=1):
            ov = combo.get("overrides") or {}
            lines.append(
                f"| {rank} | {ov.get('min_opportunity_score_buy')} | "
                f"{ov.get('min_opportunity_score_sell')} | "
                f"{ov.get('max_spread_bps')} | {ov.get('top_n')} | "
                f"{ov.get('block_low_liquidity')} | "
                f"{combo.get('adjusted_score'):.4f} | "
                f"{combo.get('net_pnl_pct'):+.4f} | "
                f"{combo.get('max_drawdown_pct'):.2f} | "
                f"{combo.get('trades_count')} |"
            )
        if best_adj:
            lines.append(
                f"\n- **Meilleure config par adjusted_score** : `{best_adj.get('overrides')}` "
                f"(adjusted={best_adj.get('adjusted_score'):.4f}, "
                f"net_pnl_pct={best_adj.get('net_pnl_pct'):+.4f}, "
                f"mdd={best_adj.get('max_drawdown_pct'):.2f}%)"
            )
        if best_pnl:
            lines.append(
                f"- **Meilleure config par net_pnl_pct brut** : `{best_pnl.get('overrides')}` "
                f"(net_pnl_pct={best_pnl.get('net_pnl_pct'):+.4f}, "
                f"mdd={best_pnl.get('max_drawdown_pct'):.2f}%)"
            )
        if recommendations:
            lines.append("\n### Recommandation prudente pour la session 15h30 CEST")
            lines.append(f"- Overrides : `{recommendations.get('overrides')}`")
            lines.append(f"- net_pnl_pct : {recommendations.get('net_pnl_pct'):+.4f}%")
            lines.append(f"- max_drawdown_pct : {recommendations.get('max_drawdown_pct'):.2f}%")
            lines.append(f"- adjusted_score : {recommendations.get('adjusted_score'):.4f}")
            lines.append(f"- trades : {recommendations.get('trades_count')}")
            lines.append(f"- rationale : {recommendations.get('rationale')}")
    else:
        lines.append("- non disponible (lancer avec `--grid-search` pour explorer la grille)")

    lines.append("\n## Avertissement")
    lines.append(
        "> Historical performance is not predictive of future results. "
        "`backtest_local_estimate` uses real OHLC data from Kraken CLI but "
        "simulates fills locally — no live or paper orders were placed."
    )
    return "\n".join(lines) + "\n"


def _write_report(payload: dict[str, Any], output_prefix: str, timestamp: str) -> tuple[Path, Path]:
    out_dir = (ROOT / output_prefix).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(output_prefix).name
    report_path = out_dir / f"{stem}_report_{timestamp}.md"
    latest_path = out_dir / f"{stem}_report_latest.md"
    text = _markdown_report(payload)
    report_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    return report_path, latest_path


# ---------------------------------------------------------------------------
# Market hours report (--market-hours-report)
# ---------------------------------------------------------------------------


_SESSION_ORDER = [
    "US_PREMARKET",
    "US_CORE",
    "US_AFTERHOURS",
    "OVERNIGHT",
    "WEEKEND",
]


def _market_hours_session_table(by_session: dict[str, Any]) -> list[str]:
    """Render a per-session table for one variant."""
    lines = [
        "| Session | candles | buy | sell | hold | approved | low_liq_blk | "
        "conf_blk | spread_blk | net_pnl_pct | mdd | best | worst |",
        "|---------|---------|-----|------|------|----------|-------------|"
        "----------|------------|-------------|-----|------|-------|",
    ]
    for sess in _SESSION_ORDER:
        agg = by_session.get(sess) or {}
        lines.append(
            f"| {sess} | {agg.get('candles_count', 0)} | "
            f"{agg.get('buy_count', 0)} | {agg.get('sell_count', 0)} | "
            f"{agg.get('hold_count', 0)} | {agg.get('approved_count', 0)} | "
            f"{agg.get('low_liquidity_blocks', 0)} | "
            f"{agg.get('confidence_blocks', 0)} | "
            f"{agg.get('spread_blocks', 0)} | "
            f"{(agg.get('net_pnl_pct') or 0):+.4f} | "
            f"{(agg.get('max_drawdown_pct') or 0):.2f} | "
            f"{agg.get('best_symbol') or '-'} | "
            f"{agg.get('worst_symbol') or '-'} |"
        )
    return lines


def _market_hours_markdown(payload: dict[str, Any]) -> str:
    symbols = payload.get("symbols") or []
    interval = payload.get("interval_min")
    candles_total = payload.get("candles_total", 0)
    candles_per_session = payload.get("candles_per_session") or {}
    variants = payload.get("variants") or {}
    var_a = variants.get("A_block_low_liquidity") or {}
    var_b = variants.get("B_allow_low_liquidity_simulation_only") or {}
    comparison = payload.get("comparison") or {}
    by_session_delta = comparison.get("by_session_delta") or {}
    rec = payload.get("recommendation") or {}

    lines: list[str] = []
    lines.append("# Market hours report — Kraken Alpha Agent\n")
    lines.append(f"- Timestamp UTC : `{payload.get('timestamp_utc')}`")
    lines.append(f"- Profil : `{payload.get('profile')}`")
    lines.append(f"- Symboles : `{', '.join(symbols) or '-'}`")
    lines.append(f"- Intervalle : `{interval}m`")
    lines.append(f"- Source : `{payload.get('source')}` ; report_kind : `{payload.get('report_kind')}`")

    lines.append("\n## Candles totales / par session\n")
    lines.append(f"- Total : **{candles_total}**")
    lines.append("\n| Session | Candles |")
    lines.append("|---------|---------|")
    for sess in _SESSION_ORDER:
        lines.append(f"| {sess} | {candles_per_session.get(sess, 0)} |")

    lines.append("\n## Variante A — LOW_LIQUIDITY bloquant (live/paper safety)\n")
    totals_a = var_a.get("totals") or {}
    lines.append(
        f"- net_pnl_pct : {(totals_a.get('net_pnl_pct') or 0):+.4f} · "
        f"trades : {totals_a.get('trades_count', 0)} "
        f"(BUY={totals_a.get('buy_count', 0)}, SELL={totals_a.get('sell_count', 0)}, "
        f"HOLD={totals_a.get('hold_count', 0)}) · "
        f"mdd : {(totals_a.get('max_drawdown_pct') or 0):.2f}% · "
        f"low_liq_blocks={totals_a.get('low_liquidity_blocks', 0)} · "
        f"conf_blocks={totals_a.get('confidence_blocks', 0)} · "
        f"spread_blocks={totals_a.get('spread_blocks', 0)}"
    )
    lines.append("")
    lines.extend(_market_hours_session_table(var_a.get("by_session") or {}))
    lines.append("")
    lines.append("### Top 5 raisons de rejet (Variante A, agrégé toutes sessions)")
    raw_top: dict[str, int] = {}
    for sess in _SESSION_ORDER:
        agg = (var_a.get("by_session") or {}).get(sess) or {}
        for entry in agg.get("top_rejection_reasons") or []:
            raw_top[entry.get("reason", "?")] = raw_top.get(entry.get("reason", "?"), 0) + int(entry.get("count", 0))
    if raw_top:
        for reason, count in sorted(raw_top.items(), key=lambda kv: kv[1], reverse=True)[:5]:
            lines.append(f"- `{reason}` × {count}")
    else:
        lines.append("- (aucun rejet enregistré)")

    lines.append("\n## Variante B — LOW_LIQUIDITY autorisé (simulation backtest UNIQUEMENT)\n")
    totals_b = var_b.get("totals") or {}
    lines.append(
        f"- net_pnl_pct : {(totals_b.get('net_pnl_pct') or 0):+.4f} · "
        f"trades : {totals_b.get('trades_count', 0)} "
        f"(BUY={totals_b.get('buy_count', 0)}, SELL={totals_b.get('sell_count', 0)}, "
        f"HOLD={totals_b.get('hold_count', 0)}) · "
        f"mdd : {(totals_b.get('max_drawdown_pct') or 0):.2f}%"
    )
    lines.append("")
    lines.extend(_market_hours_session_table(var_b.get("by_session") or {}))
    lines.append("")
    lines.append(
        "> ⚠ Variant B is for backtest analysis only. LOW_LIQUIDITY blocking "
        "remains enforced in runtime live/paper paths."
    )

    lines.append("\n## Delta A vs B\n")
    lines.append("| Session | Δ net_pnl_pct | Δ trades | Δ mdd |")
    lines.append("|---------|---------------|----------|-------|")
    for sess in _SESSION_ORDER:
        d = by_session_delta.get(sess) or {}
        lines.append(
            f"| {sess} | {(d.get('delta_net_pnl_pct') or 0):+.4f} | "
            f"{int(d.get('delta_trades_count') or 0):+d} | "
            f"{(d.get('delta_max_drawdown_pct') or 0):+.4f} |"
        )
    lines.append("")
    lines.append(
        f"- Δ global net_pnl_pct : {(comparison.get('delta_net_pnl_pct') or 0):+.4f}"
    )
    lines.append(
        f"- Δ global trades : {int(comparison.get('delta_trades_count') or 0):+d}"
    )
    lines.append(
        f"- Δ global mdd : {(comparison.get('delta_max_drawdown_pct') or 0):+.4f}"
    )

    lines.append("\n## Recommandation\n")
    keep = rec.get("keep_low_liquidity_blocking_in_runtime")
    dry_only = rec.get("allow_in_paper_dry_run_only")
    decision = "KEEP BLOCKING" if keep and not dry_only else (
        "ALLOW_IN_DRY_RUN_ONLY" if dry_only else "KEEP BLOCKING"
    )
    lines.append(f"- LOW_LIQUIDITY runtime : **{decision}**")
    lines.append(
        f"- Meilleure fenêtre CEST recommandée : **{rec.get('best_window_cest') or 'n/a'}**"
    )
    top_tickers = rec.get("best_tickers_for_1530_cest") or []
    if top_tickers:
        lines.append("- Tickers recommandés pour 15h30 CEST (US_CORE, top 5) :")
        for t in top_tickers:
            lines.append(
                f"  - {t.get('symbol')} (us_core_realized_pnl={t.get('us_core_realized_pnl')})"
            )
    else:
        lines.append("- Tickers recommandés pour 15h30 CEST : aucun signal exploitable détecté.")
    lines.append(f"- Rationale : {rec.get('rationale')}")

    lines.append("\n## Avertissement")
    lines.append(
        "> Historical performance is not predictive of future results. "
        "`backtest_local_estimate` uses real OHLC data from Kraken CLI but "
        "simulates fills locally — no live or paper orders were placed."
    )
    return "\n".join(lines) + "\n"


def _write_market_hours_report(
    payload: dict[str, Any],
    *,
    timestamp: str,
) -> dict[str, Path]:
    """Persist JSON + Markdown artefacts under ``data/market_hours_report_*``.

    These files are *separate* from ``data/backtest_*`` and never
    overwrite the base run's outputs.
    """
    out_dir = ROOT / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"market_hours_report_{timestamp}.json"
    md_path = out_dir / f"market_hours_report_{timestamp}.md"
    json_latest = out_dir / "market_hours_report_latest.json"
    md_latest = out_dir / "market_hours_report_latest.md"

    json_text = json.dumps(payload, indent=2, default=str)
    json_path.write_text(json_text, encoding="utf-8")
    json_latest.write_text(json_text, encoding="utf-8")

    md_text = _market_hours_markdown(payload)
    md_path.write_text(md_text, encoding="utf-8")
    md_latest.write_text(md_text, encoding="utf-8")

    return {
        "json": json_path,
        "md": md_path,
        "json_latest": json_latest,
        "md_latest": md_latest,
    }


def _run_market_hours_analysis(
    *,
    symbols: list[str],
    ohlc_by_symbol: dict[str, list[dict[str, float]]],
    settings: Any,
    profile: str,
    interval_minutes: int,
    initial_cash: float,
    timestamp: str,
) -> tuple[dict[str, Any], dict[str, Path]]:
    """Run variant A and B, build the report payload, and persist it."""
    candles_by_symbol: dict[str, list[backtest.Candle]] = {
        sym: backtest.build_replay_candles(sym, ohlc_by_symbol.get(sym) or [])
        for sym in symbols
    }
    variant_a = backtest.simulate_portfolio(
        symbols,
        ohlc_by_symbol,
        config=settings.config,
        profile=profile,
        initial_cash=initial_cash,
        settings=settings,
        overrides={"block_low_liquidity": True},
        interval_minutes=interval_minutes,
        record_decisions=True,
    )
    variant_b = backtest.simulate_portfolio(
        symbols,
        ohlc_by_symbol,
        config=settings.config,
        profile=profile,
        initial_cash=initial_cash,
        settings=settings,
        overrides={"block_low_liquidity": False},
        interval_minutes=interval_minutes,
        record_decisions=True,
    )
    payload = backtest.build_market_hours_report(
        symbols=symbols,
        profile=profile,
        interval_minutes=interval_minutes,
        candles_by_symbol=candles_by_symbol,
        variant_a=variant_a,
        variant_b=variant_b,
    )
    paths = _write_market_hours_report(payload, timestamp=timestamp)
    return payload, paths


def _flatten_trades(payload: dict[str, Any]) -> list[dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    portfolio = payload.get("portfolio") or {}
    by_symbol = portfolio.get("by_symbol") or {}
    for sym, res in by_symbol.items():
        for trade in res.get("trades", []) or []:
            row = dict(trade)
            row.setdefault("symbol", sym)
            row["source"] = SOURCE_LABEL
            trades.append(row)
    trades.sort(key=lambda t: (t.get("timestamp_utc"), t.get("symbol")))
    return trades


def main() -> int:
    args = _parse_args()
    if args.profile:
        os.environ["KRAKEN_ALPHA_PROFILE"] = args.profile
        reload_settings()

    settings = get_settings()
    profile = settings.active_profile

    symbols = _resolve_symbols(args)
    if not symbols:
        print("No symbols resolved; nothing to backtest.")
        return 2
    print(
        f"Backtest profile={profile} symbols={symbols} interval={args.interval}m "
        f"initial_cash={args.initial_cash} hours={args.hours} grid={args.grid_search} "
        f"include_low_liquidity={args.include_low_liquidity}"
    )

    started = time.time()
    ohlc_by_symbol, candle_counts = _fetch_ohlc_for_symbols(
        symbols,
        interval_minutes=args.interval,
        hours=args.hours,
        target_candles=args.target_candles,
    )

    overrides: dict[str, Any] = {}
    if args.include_low_liquidity:
        overrides["block_low_liquidity"] = False

    portfolio = backtest.simulate_portfolio(
        symbols,
        ohlc_by_symbol,
        config=settings.config,
        profile=profile,
        initial_cash=args.initial_cash,
        settings=settings,
        overrides=overrides or None,
        interval_minutes=args.interval,
        disable_realtime_cooldown=bool(args.disable_realtime_cooldown),
    )

    grid_result = None
    if args.grid_search:
        # The cartesian product is 672 combos. With memoization on the
        # simulation-relevant subset we run ~224 unique simulations, but
        # we still cap candles to the most recent ``--grid-candles``
        # rows to keep the sweep snappy. Set --grid-candles 0 to opt out.
        grid_ohlc = ohlc_by_symbol
        if args.grid_candles and args.grid_candles > 0:
            grid_ohlc = {
                sym: (rows[-args.grid_candles:] if isinstance(rows, list) else rows)
                for sym, rows in ohlc_by_symbol.items()
            }
        grid_result = backtest.run_grid_search(
            symbols,
            grid_ohlc,
            config=settings.config,
            profile=profile,
            grid=DEFAULT_GRID,
            initial_cash=args.initial_cash,
            settings=settings,
            interval_minutes=args.interval,
            max_combos=args.max_combos,
        )

    payload = backtest.build_run_payload(
        symbols=symbols,
        portfolio=portfolio,
        grid=grid_result,
        profile=profile,
        interval_minutes=args.interval,
        candles_per_symbol=candle_counts,
        extras={
            "include_low_liquidity": bool(args.include_low_liquidity),
            "disable_realtime_cooldown": bool(args.disable_realtime_cooldown),
            "elapsed_seconds": round(time.time() - started, 3),
        },
    )

    timestamp = time.strftime("%Y%m%dT%H%M%S")
    paths = _write_outputs(
        payload=payload,
        trades=_flatten_trades(payload),
        output_prefix=args.output_prefix,
        timestamp=timestamp,
    )
    report_path, report_latest = _write_report(payload, args.output_prefix, timestamp)

    elapsed = time.time() - started
    print(
        f"\nBacktest complete in {elapsed:.2f}s. "
        f"Net PnL = {_format_money(portfolio.net_pnl)} "
        f"({_format_pct(portfolio.net_pnl_pct)}), "
        f"trades={portfolio.trades_count} "
        f"(BUY={portfolio.buy_count}, SELL={portfolio.sell_count}, HOLD={portfolio.hold_count}), "
        f"mdd={portfolio.max_drawdown_pct:.2f}%"
    )
    print(f"JSON      : {paths['json']}")
    print(f"CSV       : {paths['csv']}")
    print(f"JSON last : {paths['json_latest']}")
    print(f"CSV last  : {paths['csv_latest']}")
    print(f"Report    : {report_path}")
    print(f"Report latest  : {report_latest}")

    if args.market_hours_report:
        mh_started = time.time()
        mh_payload, mh_paths = _run_market_hours_analysis(
            symbols=symbols,
            ohlc_by_symbol=ohlc_by_symbol,
            settings=settings,
            profile=profile,
            interval_minutes=args.interval,
            initial_cash=args.initial_cash,
            timestamp=timestamp,
        )
        rec = mh_payload.get("recommendation") or {}
        comp = mh_payload.get("comparison") or {}
        decision = (
            "KEEP BLOCKING"
            if rec.get("keep_low_liquidity_blocking_in_runtime")
            and not rec.get("allow_in_paper_dry_run_only")
            else (
                "ALLOW_IN_DRY_RUN_ONLY"
                if rec.get("allow_in_paper_dry_run_only")
                else "KEEP BLOCKING"
            )
        )
        print(
            f"\nMarket-hours analysis complete in {time.time() - mh_started:.2f}s."
        )
        print(
            f"delta net_pnl_pct (B-A) : {comp.get('delta_net_pnl_pct'):+.4f} | "
            f"delta trades : {comp.get('delta_trades_count'):+d} | "
            f"delta mdd : {comp.get('delta_max_drawdown_pct'):+.4f}"
        )
        print(f"LOW_LIQUIDITY runtime : {decision}")
        print(f"Best window CEST      : {rec.get('best_window_cest')}")
        top = rec.get("best_tickers_for_1530_cest") or []
        if top:
            print("Top tickers US_CORE   : " + ", ".join(t.get("symbol", "?") for t in top))
        print(f"Market hours JSON      : {mh_paths['json']}")
        print(f"Market hours JSON last : {mh_paths['json_latest']}")
        print(f"Market hours MD        : {mh_paths['md']}")
        print(f"Market hours MD last   : {mh_paths['md_latest']}")

    if grid_result is not None:
        print(
            f"\nGrid search evaluated {grid_result.combos_evaluated} combos "
            f"in {grid_result.duration_seconds:.2f}s."
        )
        best = grid_result.best_by_adjusted_score
        if best:
            print(
                "Best by adjusted_score : "
                f"{best.overrides} "
                f"(net_pnl_pct={best.portfolio.net_pnl_pct:+.4f}, "
                f"mdd={best.portfolio.max_drawdown_pct:.2f}%, "
                f"adjusted={best.adjusted_score:.4f})"
            )
        cautious = grid_result.cautious_recommendation
        if cautious:
            print(
                "Cautious recommendation : "
                f"{cautious.get('overrides')} "
                f"(net_pnl_pct={cautious.get('net_pnl_pct'):+.4f}, "
                f"mdd={cautious.get('max_drawdown_pct'):.2f}%)"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
