"""Paper-trading smoke test (read-only by default).

Default behaviour (zero side effects):
- read ``kraken paper status`` via the wrapper
- if uninitialized, print the exact ``paper init`` command for the user to run manually
- if initialized, also read ``paper balance``, ``paper orders``, ``paper history``
  and persist them as JSON for the audit bundle

Explicit opt-in flags (require the user to type them):
- ``--init``              run ``paper init --balance 10000 --currency USD --yes``
- ``--place-test-order``  place a single mini paper buy for AAPLx (0.001)

The script never places a *live* order and never mutates the paper account
unless the corresponding flag is present.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import kraken_cli
from src.logger import get_logger
from src.universe import pair_format
from src.utils import utc_now_iso

logger = get_logger("paper_smoke_test")

TEST_ORDER_SYMBOL = "AAPLx"
TEST_ORDER_VOLUME = 0.001


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Paper trading smoke test (read-only by default).")
    p.add_argument(
        "--init", action="store_true",
        help="run `paper init --balance 10000 --currency USD --yes` (paper only)",
    )
    p.add_argument(
        "--place-test-order", action="store_true",
        help=f"place a mini paper buy for {TEST_ORDER_SYMBOL}/USD ({TEST_ORDER_VOLUME})",
    )
    p.add_argument(
        "--initial-balance", type=float, default=10_000.0,
        help="starting balance passed to `paper init` (default 10000)",
    )
    p.add_argument(
        "--currency", type=str, default="USD",
        help="quote currency for `paper init` (default USD)",
    )
    p.add_argument(
        "--output-dir", type=str, default="data",
        help="directory for the JSON report (default data/)",
    )
    return p.parse_args()


def _is_initialised(payload: dict) -> bool:
    """Heuristic: a successful status payload that does not flag uninitialised."""
    if not isinstance(payload, dict):
        return False
    if payload.get("using_mock"):
        return False
    data = payload.get("data")
    if not isinstance(data, dict):
        return False
    note = (payload.get("note") or "").lower()
    if "not initialised" in note or "not initialized" in note:
        return False
    # Common keys returned by `kraken paper status` once initialised.
    for key in ("balance", "balances", "cash", "equity"):
        if key in data:
            return True
    return bool(data)


def _persist(report: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%S")
    path = out_dir / f"paper_smoke_test_{ts}.json"
    path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return path


def main() -> int:
    args = _parse_args()
    out_dir = Path(args.output_dir)

    print(f"[paper-smoke] {utc_now_iso()} starting")
    print("[paper-smoke] reading `kraken paper status` (read-only)...")

    status = kraken_cli.fetch_paper_status()
    print(json.dumps(status, indent=2, default=str)[:1500])

    report: dict = {
        "generated_at": utc_now_iso(),
        "status": status,
        "initialised": False,
        "balance": None,
        "orders": None,
        "history": None,
        "init_action": None,
        "test_order_action": None,
    }

    initialised = _is_initialised(status)
    report["initialised"] = initialised

    if not initialised:
        cmd = (
            f"kraken paper init --balance {args.initial_balance:g} "
            f"--currency {args.currency} --yes"
        )
        print("\n[paper-smoke] Paper account is NOT initialised.")
        print("[paper-smoke] To initialize, run manually (one-time):")
        print(f"    {cmd}")
        if args.init:
            print("\n[paper-smoke] --init flag detected, initializing now...")
            result = kraken_cli.paper_init(args.initial_balance, args.currency)
            report["init_action"] = {
                "command": " ".join(result.command),
                "ok": result.ok,
                "stderr": result.stderr[:500] if result.stderr else "",
                "status": result.status,
            }
            if not result.ok:
                print(f"[paper-smoke] paper init FAILED: {result.stderr[:200]}")
            else:
                print("[paper-smoke] paper init OK. Re-reading status...")
                status = kraken_cli.fetch_paper_status()
                report["status"] = status
                initialised = _is_initialised(status)
                report["initialised"] = initialised

    if initialised:
        print("\n[paper-smoke] Paper account is initialised. Fetching read-only data...")
        report["balance"] = kraken_cli.fetch_paper_balance()
        report["orders"] = kraken_cli.fetch_paper_orders()
        report["history"] = kraken_cli.fetch_paper_history()

        if args.place_test_order:
            pair = pair_format(TEST_ORDER_SYMBOL, args.currency)
            print(f"\n[paper-smoke] --place-test-order detected. Placing 1 mini PAPER buy {pair} {TEST_ORDER_VOLUME}...")
            result = kraken_cli.paper_place_order(
                symbol_pair=pair,
                action="BUY",
                volume=TEST_ORDER_VOLUME,
                order_type="market",
            )
            report["test_order_action"] = {
                "command": " ".join(result.command),
                "ok": result.ok,
                "stderr": result.stderr[:500] if result.stderr else "",
                "stdout_json": result.stdout_json,
                "status": result.status,
            }
            if result.ok:
                print(f"[paper-smoke] test paper order OK (paper, not live).")
            else:
                print(f"[paper-smoke] test paper order FAILED: {result.stderr[:200]}")

    path = _persist(report, out_dir)
    print(f"\n[paper-smoke] report written to {path}")
    print(f"[paper-smoke] initialised={initialised}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
