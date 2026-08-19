"""Event study: monthly options expiry (third Friday) vs crypto forward vol/return.

Uses :func:`src.signals.options_expiry.build_monthly_options_expiry_events`
on daily OHLC only — no Deribit API/collector required.

Read-only harness — no trading, no config.yaml changes.

Usage
-----
.. code-block:: powershell

    python scripts/event_study_deribit_expiry.py
    python scripts/event_study_deribit_expiry.py --ticker ETH --output-json out.json
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _event_study_common import (  # noqa: E402
    add_common_event_study_args,
    fetch_daily_ohlc_from_args,
    run_event_study_pipeline,
    write_json_report,
)

from src.crypto_ohlc_rest import CryptoOHLCFetchError
from src.signals.options_expiry import build_monthly_options_expiry_events

TAG = "deribit_expiry"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Event study: third-Friday monthly options expiry (calendar) "
            "vs forward crypto return/vol (read-only)."
        ),
    )
    add_common_event_study_args(p, default_ticker="BTC")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    hypothesis = (
        f"monthly options expiry (3rd Friday UTC) → "
        f"elevated forward {args.ticker} realized_vol / return"
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

    events = build_monthly_options_expiry_events(candles)
    print(f"[{TAG}] monthly expiry events: {len(events)}")

    code, report = run_event_study_pipeline(
        tag=TAG,
        hypothesis=hypothesis,
        candles=candles,
        events=events,
        n_placebos=args.n_placebos,
        seed=args.seed,
        alpha=args.alpha,
    )
    report.update({"ticker": args.ticker, "window_days": args.days})

    if args.output_json:
        write_json_report(args.output_json, report, tag=TAG)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
