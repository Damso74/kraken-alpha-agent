"""Continuous agent loop. Handles Ctrl+C gracefully."""

from __future__ import annotations

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
    interval = settings.config.trading.cycle_interval_seconds
    print(
        f"Starting {settings.config.competition.agent_codename} "
        f"mode={settings.env.trading_mode} interval={interval}s. Ctrl+C to stop."
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
