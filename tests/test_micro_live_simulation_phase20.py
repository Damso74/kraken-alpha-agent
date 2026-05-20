"""Integration tests for micro-live simulation (Phase 20)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_micro_live_simulation_cli(tmp_path: Path) -> None:
    out = tmp_path / "sim"
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "scripts" / "run_micro_live_simulation.py"),
            "--asset",
            "BTC",
            "--capital",
            "10",
            "--notional",
            "5",
            "--grant-manual-approval",
            "--output-dir",
            str(out),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    payload = json.loads((out / "dry_run_orders.json").read_text(encoding="utf-8"))
    assert payload["real_order_submitted"] is False
    assert payload["kraken_called"] is False
    assert (out / "guardrail_report.md").is_file()
