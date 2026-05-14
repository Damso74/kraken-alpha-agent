"""Rank the xStocks allowlist by opportunity score.

This script is **safe and read-only**: it calls ``kraken ticker / ohlc /
orderbook / trades`` (with ``--asset-class tokenized_asset`` injected by
the wrapper) and never places an order. When the CLI is unavailable, the
wrapper falls back to deterministic mock data so the script always finishes
and writes its output files.

Usage examples::

    python scripts/rank_xstocks.py
    python scripts/rank_xstocks.py --top 10 --json-only
    python scripts/rank_xstocks.py --profile aggressive_competition
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Allow running from anywhere: `python scripts/rank_xstocks.py`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import market_data
from src.config import get_settings, reload_settings
from src.logger import get_logger
from src.ranking import (
    RankedSymbol,
    apply_filters,
    compute_symbol_rank,
    select_top_n,
    sort_ranking,
)
from src.universe import get_universe_tickers, pair_format
from src.utils import utc_now_iso

logger = get_logger("rank_xstocks")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Rank xStocks by opportunity score (read-only).")
    p.add_argument("--top", type=int, default=5, help="rows to print in the terminal (default 5)")
    p.add_argument("--profile", type=str, default=None, help="override active profile for this run")
    p.add_argument("--json-only", action="store_true", help="only print the JSON file path")
    p.add_argument("--no-csv", action="store_true", help="skip CSV export")
    p.add_argument("--output-dir", type=str, default="data", help="output directory (default: data/)")
    return p.parse_args()


def _rank_one(symbol: str, quote: str) -> tuple[RankedSymbol, list[str]]:
    """Fetch all four endpoints for ``symbol`` and build the RankedSymbol."""
    errors: list[str] = []
    ticker: dict = {}
    candles: list = []
    book: dict | None = None
    trades: dict | None = None

    try:
        ticker = market_data.get_ticker(symbol, quote)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ticker: {exc}")
    try:
        candles = market_data.get_ohlc(symbol, quote, interval_minutes=60, count=24)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"ohlc: {exc}")
    try:
        book = market_data.get_orderbook(symbol, quote, count=10)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"orderbook: {exc}")
    try:
        trades = market_data.get_trades(symbol, quote, count=50)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"trades: {exc}")

    ranked = compute_symbol_rank(
        symbol,
        pair=pair_format(symbol, quote),
        ticker=ticker,
        candles=candles,
        orderbook=book,
        trades=trades,
    )
    return ranked, errors


def _print_top(rows: list[RankedSymbol], n: int) -> None:
    header = (
        f"{'rank':>4} {'symbol':<8} {'last':>10} {'spread_bps':>10} "
        f"{'volume':>12} {'tc':>4} {'mom':>7} {'liq':>5} {'opp':>7}"
    )
    print(header)
    print("-" * len(header))
    for r in rows[:n]:
        print(
            f"{r.rank:>4} {r.symbol:<8} {r.last_price:>10.4f} "
            f"{r.spread_bps:>10.1f} {r.volume_24h:>12.2f} "
            f"{r.trade_count_recent:>4d} {r.momentum_score:>+7.3f} "
            f"{r.liquidity_score:>5.2f} {r.opportunity_score:>+7.3f}"
        )


def _write_outputs(rows: list[RankedSymbol], out_dir: Path, write_csv: bool) -> tuple[Path, Path | None]:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    json_path = out_dir / f"xstocks_rank_{ts}.json"
    csv_path = out_dir / f"xstocks_rank_{ts}.csv" if write_csv else None

    payload = {
        "generated_at": utc_now_iso(),
        "profile": get_settings().active_profile,
        "count": len(rows),
        "rows": [asdict(r) for r in rows],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Also keep a stable "latest" copy so the dashboard can read it
    # without having to scan the directory.
    (out_dir / "xstocks_rank_latest.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )

    if csv_path is not None and rows:
        fields = list(asdict(rows[0]).keys())
        with csv_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: getattr(r, k) for k in fields})
    return json_path, csv_path


def main() -> int:
    args = _parse_args()
    if args.profile:
        os.environ["KRAKEN_ALPHA_PROFILE"] = args.profile
        reload_settings()
    settings = get_settings()
    uni_cfg = settings.config.universe
    quote = uni_cfg.quote

    symbols = get_universe_tickers()
    print(
        f"Ranking {len(symbols)} xStocks for profile={settings.active_profile} "
        f"(mode={uni_cfg.mode}, quote={quote})..."
    )

    rank_rows: list[RankedSymbol] = []
    error_map: dict[str, list[str]] = {}
    started = time.time()
    for sym in symbols:
        try:
            ranked, errors = _rank_one(sym, quote)
        except Exception as exc:  # noqa: BLE001
            logger.exception("ranking failed for %s: %s", sym, exc)
            error_map[sym] = [f"fatal: {exc}"]
            continue
        if errors:
            error_map[sym] = errors
        rank_rows.append(ranked)

    annotated = apply_filters(
        rank_rows,
        max_spread_bps=uni_cfg.max_spread_bps,
        min_volume=uni_cfg.min_volume,
        min_trade_count=uni_cfg.min_trade_count,
    )
    selected = select_top_n(annotated, top_n=uni_cfg.top_n)
    sorted_rows = sort_ranking(rank_rows)

    elapsed = time.time() - started
    out_dir = Path(args.output_dir)
    json_path, csv_path = _write_outputs(sorted_rows, out_dir, write_csv=not args.no_csv)

    skipped = [r for r in annotated if r.skipped_reason]
    print(
        f"Ranked {len(rank_rows)} symbols in {elapsed:.1f}s, "
        f"{len(selected)} selected after filters, {len(skipped)} skipped."
    )
    if not args.json_only:
        _print_top(sorted_rows, args.top)
        if skipped:
            print("\nSkipped:")
            for r in skipped:
                print(f"  - {r.symbol}: {r.skipped_reason}")
        if error_map:
            print("\nPartial errors (continued anyway):")
            for sym, errs in error_map.items():
                print(f"  - {sym}: {'; '.join(errs)[:200]}")
    print(f"\nJSON: {json_path}")
    if csv_path is not None:
        print(f"CSV : {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
