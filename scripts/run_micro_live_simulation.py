#!/usr/bin/env python3
"""Micro-live simulation — dry-run only, never submits real orders (Phase 20)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.kill_switch import (
    GuardrailConfig,
    GuardrailState,
    evaluate_guardrails,
    guardrail_report,
)
from src.bot.live_adapter_dry_run import (
    LiveOrderIntent,
    dry_run_submit_order,
    intent_to_dict,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Micro-live dry-run simulation (NO real orders)")
    p.add_argument("--asset", default="BTC")
    p.add_argument("--capital", type=float, default=10.0)
    p.add_argument("--dry-run-only", action="store_true", default=True)
    p.add_argument("--require-manual-approval", action="store_true", default=True)
    p.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "reports" / "micro_live_sim_phase20",
    )
    p.add_argument("--side", default="buy", choices=["buy", "sell"])
    p.add_argument("--notional", type=float, default=5.0)
    p.add_argument("--grant-manual-approval", action="store_true", default=False)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    sym = args.asset.upper()
    config = GuardrailConfig(
        max_capital_usd=min(20.0, max(5.0, args.capital)),
        max_position_usd=min(10.0, args.capital),
        manual_approval_required=args.require_manual_approval,
        dry_run_passed=args.dry_run_only,
    )
    state = GuardrailState(
        starting_capital_usd=args.capital,
        current_equity_usd=args.capital,
        manual_approval_granted=args.grant_manual_approval,
    )

    price = 100_000.0 if sym == "BTC" else 3000.0
    qty = args.notional / price
    intent = LiveOrderIntent(
        symbol=sym,
        side=args.side,
        quantity=qty,
        notional_usd=args.notional,
        price_hint=price,
        strategy="micro_live_sim",
        reason="phase20_dry_run",
    )

    guard = evaluate_guardrails(
        config=config,
        state=state,
        symbol=sym,
        notional_usd=args.notional,
    )

    result = dry_run_submit_order(
        intent,
        max_notional_usd=config.max_capital_usd,
        manual_approval=state.manual_approval_granted,
    )

    if not guard.allowed:
        result_status = "blocked"
        result_message = guard.reason
    else:
        result_status = result.status
        result_message = result.message

    payload = {
        "phase": 20,
        "dry_run_only": True,
        "real_order_submitted": False,
        "kraken_called": False,
        "guardrail": guardrail_report(config, state),
        "guardrail_decision": {"allowed": guard.allowed, "reason": guard.reason},
        "order_result": {
            "status": result_status,
            "message": result_message,
            "intent": intent_to_dict(intent),
            "estimated_fee_usd": result.estimated_fee_usd,
        },
    }

    (args.output_dir / "dry_run_orders.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )
    with (args.output_dir / "intents.jsonl").open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(intent_to_dict(intent)) + "\n")

    report_lines = [
        "# Micro-live guardrail report (Phase 20)",
        "",
        "**NO-GO by default** — dry-run simulation only.",
        "",
        f"- Guardrail allowed: {guard.allowed}",
        f"- Guardrail reason: {guard.reason}",
        f"- Order status: {result_status}",
        f"- Message: {result_message}",
        f"- Real order submitted: **NO**",
        f"- Kraken API called: **NO**",
        "",
    ]
    (args.output_dir / "guardrail_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
