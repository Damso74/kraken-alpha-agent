"""Event study: Ethereum gas congestion (fast gwei z-score) vs ETH forward returns.

The Etherscan collector returns a **snapshot** only. This script reads a
daily history from ``data/collector_cache/etherscan_gas_history.json``
(append-only when not ``--use-cache-only``). Populate history over time or
seed the cache before offline runs.

Read-only — no trading, no config.yaml changes.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_eth_gas.py
    python scripts/event_study_eth_gas.py --use-cache-only
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    REPO_ROOT,
    add_common_event_study_args,
    align_events_to_daily_candles,
    fetch_daily_ohlc_from_args,
    run_event_study_pipeline,
    write_json_report,
)
from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.data.collectors._common import CollectorError, load_json_cache, save_json_cache
from src.data.collectors.etherscan import (
    BLOCKED_MISSING_GAS_HISTORY,
    default_etherscan_cache_path,
    fetch_gas_oracle,
)
from src.signals.eth_gas_congestion import build_eth_gas_congestion_events

TAG = "eth_gas"
DEFAULT_HISTORY_CACHE = REPO_ROOT / "data" / "collector_cache" / "etherscan_gas_history.json"
DEFAULT_SNAPSHOT_CACHE = REPO_ROOT / default_etherscan_cache_path()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: ETH gas congestion z-score vs forward ETH "
            "returns/vol (read-only; needs gas history cache)."
        ),
    )
    add_common_event_study_args(p, default_ticker="ETH")
    p.add_argument(
        "--z-threshold",
        type=float,
        default=1.5,
        help="Minimum fast-gwei z-score (default 1.5).",
    )
    p.add_argument(
        "--lookback",
        type=int,
        default=180,
        help="Rolling z-score window in observations (default 180).",
    )
    p.add_argument(
        "--history-cache",
        type=Path,
        default=DEFAULT_HISTORY_CACHE,
        help="JSON file with daily gas rows (timestamp, fast_gwei).",
    )
    p.add_argument(
        "--snapshot-cache",
        type=Path,
        default=DEFAULT_SNAPSHOT_CACHE,
        help="Etherscan snapshot cache for live oracle fetch.",
    )
    return p.parse_args()


def _normalize_daily_row(row: dict[str, Any]) -> dict[str, Any] | None:
    ts = row.get("timestamp")
    fast = row.get("fast_gwei")
    if not isinstance(ts, int):
        return None
    try:
        gwei = float(fast)
    except (TypeError, ValueError):
        return None
    if gwei < 0:
        return None
    d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
    ts_norm = int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())
    return {"timestamp": ts_norm, "fast_gwei": gwei, "source": "etherscan_gas_history"}


def _load_history(path: Path) -> list[dict[str, Any]]:
    raw = load_json_cache(path)
    entries = raw.get("entries") or {}
    daily = entries.get("daily") if isinstance(entries, dict) else None
    if not isinstance(daily, list):
        return []
    out: list[dict[str, Any]] = []
    for item in daily:
        if isinstance(item, dict):
            norm = _normalize_daily_row(item)
            if norm is not None:
                out.append(norm)
    out.sort(key=lambda r: r["timestamp"])
    return out


def _merge_history(
    existing: list[dict[str, Any]], fresh: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_ts: dict[int, dict[str, Any]] = {int(r["timestamp"]): r for r in existing}
    for row in fresh:
        by_ts[int(row["timestamp"])] = row
    return [by_ts[k] for k in sorted(by_ts)]


def _persist_history(path: Path, rows: list[dict[str, Any]]) -> None:
    save_json_cache(
        path,
        {
            "source": "etherscan_gas_history",
            "entries": {"daily": rows},
        },
    )


def _fetch_and_merge_snapshot(
    history: list[dict[str, Any]],
    snapshot_cache: Path,
) -> list[dict[str, Any]]:
    snap_rows = fetch_gas_oracle(cache_path=snapshot_cache)
    fresh: list[dict[str, Any]] = []
    for row in snap_rows:
        norm = _normalize_daily_row(dict(row))
        if norm is not None:
            fresh.append(norm)
    if not fresh:
        return history
    return _merge_history(history, fresh)


def main() -> int:
    args = parse_args()
    hypothesis = (
        f"ETH fast-gwei congestion z>={args.z_threshold} → "
        f"forward {args.ticker} return/vol"
    )

    history = _load_history(args.history_cache)
    if not args.use_cache_only:
        try:
            history = _fetch_and_merge_snapshot(history, args.snapshot_cache)
            _persist_history(args.history_cache, history)
        except CollectorError as exc:
            print(f"[{TAG}] WARNING snapshot fetch failed: {exc}", file=sys.stderr)
    elif not history:
        print(
            f"[{TAG}] FATAL {BLOCKED_MISSING_GAS_HISTORY} "
            f"(use_cache_only, path={args.history_cache})",
            file=sys.stderr,
        )
        return 2

    print(f"[{TAG}] gas history rows: {len(history)}")
    if len(history) < args.lookback + 1:
        print(
            f"[{TAG}] FATAL need at least {args.lookback + 1} daily gas "
            f"observations (have {len(history)}). The Etherscan collector "
            "only provides snapshots — append to the history cache over time "
            f"or run without --use-cache-only to record today's oracle.",
            file=sys.stderr,
        )
        return 2

    raw_events = build_eth_gas_congestion_events(
        history,
        z_threshold=args.z_threshold,
        lookback=args.lookback,
    )

    try:
        candles = fetch_daily_ohlc_from_args(args)
    except CryptoOHLCFetchError as exc:
        print(f"[{TAG}] FATAL Kraken OHLC failed: {exc}", file=sys.stderr)
        return 3
    if not candles:
        print(f"[{TAG}] FATAL 0 candles", file=sys.stderr)
        return 3
    print(f"[{TAG}] {args.ticker} daily OHLC: {len(candles)} candles")

    events = align_events_to_daily_candles(raw_events, candles)

    code, report = run_event_study_pipeline(
        tag=TAG,
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=args.n_placebos,
        seed=args.seed,
        alpha=args.alpha,
    )
    report.update(
        {
            "gas_history_rows": len(history),
            "z_threshold": args.z_threshold,
            "lookback": args.lookback,
            "ticker": args.ticker,
            "window_days": args.days,
            "history_cache": str(args.history_cache),
        }
    )

    if args.output_json:
        write_json_report(args.output_json, report, tag=TAG)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
