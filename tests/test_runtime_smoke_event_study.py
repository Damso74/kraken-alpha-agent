"""Runtime smoke: event-study CLI --help and --use-cache-only (no network).

Uses empty cache paths so collectors fail before Kraken OHLC or placebo work.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
SMOKE_DIR = REPO_ROOT / "reports" / "runtime_smoke"


def _run_script(
    script: str,
    *args: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd = [PYTHON, str(REPO_ROOT / script), *args]
    merged = {"PYTHONIOENCODING": "utf-8", **(env or {})}
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={**subprocess.os.environ, **merged},
        timeout=60,
    )


@pytest.mark.parametrize(
    "script",
    [
        "scripts/event_study_stablecoins.py",
        "scripts/event_study_wikipedia.py",
        "scripts/event_study_eth_gas.py",
        "scripts/event_study_exchange_status.py",
        "scripts/event_study_calendar.py",
        "scripts/event_study_deribit_expiry.py",
        "scripts/demo_event_study.py",
    ],
)
def test_event_study_script_help_exits_zero(script: str) -> None:
    proc = _run_script(script, "--help")
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize(
    "script,extra_args,needle",
    [
        (
            "scripts/event_study_stablecoins.py",
            ("--cache-path", str(SMOKE_DIR / "_pytest_empty_defillama.json")),
            "use_cache_only",
        ),
        (
            "scripts/event_study_wikipedia.py",
            ("--cache-path", str(SMOKE_DIR / "_pytest_empty_wikimedia.json")),
            "use_cache_only",
        ),
        (
            "scripts/event_study_exchange_status.py",
            ("--cache-path", str(SMOKE_DIR / "_pytest_empty_status.json")),
            "use_cache_only",
        ),
    ],
)
def test_use_cache_only_fails_before_network(
    script: str,
    extra_args: tuple[str, ...],
    needle: str,
) -> None:
    out_json = SMOKE_DIR / f"_pytest_{Path(script).stem}_out.json"
    if out_json.exists():
        out_json.unlink()
    proc = _run_script(
        script,
        "--use-cache-only",
        "--output-json",
        str(out_json),
        "--days",
        "30",
        "--n-placebos",
        "5",
        *extra_args,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert needle in proc.stderr.lower() or needle in proc.stderr
    assert not out_json.exists()


def test_eth_gas_use_cache_only_missing_history() -> None:
    missing = SMOKE_DIR / "_pytest_empty_gas_history.json"
    proc = _run_script(
        "scripts/event_study_eth_gas.py",
        "--use-cache-only",
        "--history-cache",
        str(missing),
        "--days",
        "30",
        "--n-placebos",
        "5",
    )
    assert proc.returncode == 2
    assert (
        "blocked: missing historical gas cache" in proc.stderr.lower()
        or "use_cache_only" in proc.stderr.lower()
        or "no gas history" in proc.stderr.lower()
    )


def test_demo_use_cache_only_missing_fear_greed_cache(tmp_path: Path) -> None:
    empty_fg = tmp_path / "fear_greed_empty.json"
    proc = _run_script(
        "scripts/demo_event_study.py",
        "--use-cache-only",
        "--cache-path",
        str(empty_fg),
        "--days",
        "30",
        "--n-placebos",
        "5",
    )
    assert proc.returncode == 2
    assert "use_cache_only" in proc.stderr.lower() or "cache" in proc.stderr.lower()


def test_calendar_help_lists_use_cache_only_flag() -> None:
    proc = _run_script("scripts/event_study_calendar.py", "--help")
    assert proc.returncode == 0
    assert "--use-cache-only" in proc.stdout
