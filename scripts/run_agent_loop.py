"""Continuous agent loop. Handles Ctrl+C gracefully."""

from __future__ import annotations

import os
import signal
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_settings  # noqa: E402
from src.logger import setup_logging  # noqa: E402
from src.main import run_loop  # noqa: E402


def main() -> int:
    setup_logging()
    settings = get_settings()
    cfg_interval = settings.config.trading.cycle_interval_seconds
    env_override = os.environ.get("LOOP_INTERVAL_SECONDS")
    interval = cfg_interval
    if env_override:
        try:
            interval = max(2, int(env_override))
        except ValueError:
            interval = cfg_interval
    profile = settings.active_profile
    print(
        f"Starting {settings.config.competition.agent_codename} "
        f"mode={settings.env.trading_mode} profile={profile} "
        f"interval={interval}s (cfg={cfg_interval}, env={env_override or 'unset'}). "
        f"Ctrl+C to stop."
    )
    stop = threading.Event()

    def handle(*_):
        print("\nstopping... (current cycle will finish)")
        stop.set()

    signal.signal(signal.SIGINT, handle)
    try:
        signal.signal(signal.SIGTERM, handle)
    except (AttributeError, ValueError):
        pass  # Windows console may not expose SIGTERM
    run_loop(stop_event=stop)
    print("agent stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
