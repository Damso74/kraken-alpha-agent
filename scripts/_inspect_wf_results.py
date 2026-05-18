"""Read-only inspector for walk-forward result JSONs.

Quick summariser used during the multi-interval crypto sweep to extract
test-window distribution stats from a walk-forward output file. Pure
stdlib, no side effects, no Kraken interaction.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect walk-forward result JSON")
    parser.add_argument("path", type=str)
    parser.add_argument("--top", type=int, default=3)
    args = parser.parse_args()

    p = json.loads(Path(args.path).read_text(encoding="utf-8"))
    ev = p.get("evaluated", [])
    print(f"file              : {args.path}")
    print(f"preset            : {p.get('preset', 'default')}")
    print(f"interval_minutes  : {p.get('interval_minutes')}")
    print(f"grid_size         : {p.get('grid_size')}")
    print(f"survivors_count   : {p.get('survivors_count')}")
    print(f"train_window_iso  : {p.get('train_window_iso')}")
    print(f"test_window_iso   : {p.get('test_window_iso')}")
    print(f"filter            : {p.get('filter')}")

    if not ev:
        print("(empty evaluated list)")
        return 0

    def stat(field_path):
        head, tail = field_path.split(".")
        return [c[head][tail] for c in ev]

    for label, key in [
        ("TEST  PnL", "test.net_pnl_usd"),
        ("TEST  WR ", "test.win_rate"),
        ("TEST  MDD", "test.max_drawdown_pct"),
        ("TEST  TRD", "test.trades_count"),
        ("TRAIN PnL", "train.net_pnl_usd"),
        ("TRAIN WR ", "train.win_rate"),
        ("TRAIN MDD", "train.max_drawdown_pct"),
        ("TRAIN TRD", "train.trades_count"),
    ]:
        vals = stat(key)
        try:
            print(
                f"{label}  min={min(vals):+.4f}  median={statistics.median(vals):+.4f}  max={max(vals):+.4f}"
            )
        except TypeError:
            print(f"{label}  min={min(vals)}  median={statistics.median(vals)}  max={max(vals)}")

    ev_sorted = sorted(ev, key=lambda c: c["test"]["net_pnl_usd"], reverse=True)
    print(f"\nTop {args.top} by TEST PnL:")
    for i, c in enumerate(ev_sorted[: args.top]):
        params = c["params"]
        t = c["test"]
        tr = c["train"]
        print(
            f"  #{i + 1} params={params} | "
            f"test: pnl={t['net_pnl_usd']:+.4f} wr={t['win_rate']:.4f} "
            f"mdd={t['max_drawdown_pct']:.4f} trades={t['trades_count']} | "
            f"train: pnl={tr['net_pnl_usd']:+.4f} wr={tr['win_rate']:.4f} "
            f"trades={tr['trades_count']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
