"""Probe the Kraken CLI installation and run one safe read-only call.

Never prints any secret. Suitable for CI / pre-flight checks.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import safe_env_snapshot  # noqa: E402
from src.kraken_cli import (  # noqa: E402
    fetch_ticker,
    is_installed,
    kraken_diagnostics,
)
from src.logger import setup_logging  # noqa: E402


def main() -> int:
    setup_logging()
    diag = kraken_diagnostics()
    print("kraken_cli:", json.dumps(diag, indent=2))
    print("env:", json.dumps(safe_env_snapshot(), indent=2))

    if not is_installed():
        print(
            "\nKraken CLI is not on PATH. "
            "Install it from https://www.kraken.com/kraken-cli before going to paper/live mode.\n"
            "The agent will keep working with the mock data fallback for now."
        )
        return 0

    sample = fetch_ticker("AAPLx")
    print("\nsample ticker (AAPLx):")
    print(json.dumps(sample, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
