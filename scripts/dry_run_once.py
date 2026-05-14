"""Run exactly one full dry-run cycle and print a short summary."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_settings  # noqa: E402
from src.logger import setup_logging  # noqa: E402
from src.main import run_one_cycle  # noqa: E402


def main() -> int:
    setup_logging()
    settings = get_settings()
    if settings.env.trading_mode.lower() != "dry_run":
        print(
            f"WARNING: TRADING_MODE={settings.env.trading_mode!r} — "
            "forcing dry_run for this script is recommended.\n"
        )
    print(f"Agent: {settings.config.competition.agent_codename}")
    print(f"Mode: {settings.env.trading_mode} (config_source={settings.config_source})")
    print(f"Universe: {len(settings.config.universe.symbols)} symbols\n")

    decisions = run_one_cycle()

    actionable = [d for d in decisions if d.action != "HOLD"]
    approved = [d for d in decisions if d.risk.approved]
    print("\n=== Cycle summary ===")
    print(f"decisions:   {len(decisions)}")
    print(f"actionable:  {len(actionable)} (BUY/SELL signals)")
    print(f"approved:    {len(approved)}")
    print(f"db:          {settings.absolute_path(settings.env.database_path)}")
    print(f"decisions:   {settings.absolute_path(settings.env.decisions_log_path)}")
    if decisions:
        d0 = decisions[0]
        print(
            f"\nfirst decision -> {d0.symbol} action={d0.action} "
            f"score={d0.final_score:+.3f} conf={d0.confidence:.2f} regime={d0.regime}"
        )
        print(f"  risk approved: {d0.risk.approved}; reasons={d0.risk.reasons}")
        print(f"  execution status: {d0.execution.status} mode={d0.execution.mode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
