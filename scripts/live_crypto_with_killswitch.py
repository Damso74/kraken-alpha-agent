"""Operator-facing entry point for the option-D live crypto session.

Strict contract
---------------
- This script never auto-starts. It refuses to launch unless the operator
  passes ``--i-understand-the-risks`` explicitly.
- It validates that the live env triple opt-in is set
  (``TRADING_MODE=live`` + ``LIVE_TRADING=true`` + ``ALLOW_LIVE_ORDERS=true``).
- It validates that ``KRAKEN_ALPHA_PROFILE`` resolves to a futures-engine
  profile that exists in ``config.yaml`` (default name:
  ``live_crypto_aggressive_capped``).
- It validates that the Kraken Futures key is present
  (``KRAKEN_FUTURES_API_KEY``).
- It spawns ``scripts/run_agent_loop.py`` as a child subprocess and
  monitors PnL every ``--poll-interval-seconds`` (default 10s).
- A cumulative session PnL of ``-5.00 USD`` (overridable but clamped to
  ``≤ −0.01``) triggers:

  1. ``kraken futures cancel-after 1`` (dead-man's switch acceleration),
  2. ``reduce-only`` market sell on every open long,
  3. ``SIGTERM`` to the agent subprocess,
  4. structured JSON log line in ``data/killswitch.log``,
  5. exit code ``1``.

Soft cutoffs (clean exit, code ``0``):

- ``--max-duration-hours`` ceiling reached,
- CEST cut-off ``21:55`` (matches the friday-end-of-day rule),
- ``SIGINT``/``SIGTERM`` from the operator.

In every case (trigger or clean exit) the flatten routine fires, so the
script never leaves a position behind.

Note on EV
----------
The walk-forward in ``data/walk_forward_crypto_results.json`` returned
**zero survivors** on the deterministic strategy stack for the 5-symbol
crypto Perp universe over the last 90 days. The corresponding profile
``live_crypto_aggressive_capped`` was therefore intentionally **not**
created — this script will refuse to launch with a clear error message
until a future tuning round produces a winner. Forcing the activation
on top of an EV-negative grid would be reckless; see
``docs/OPTION_D_ACTIVATION.md`` for the formal protocol.
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from datetime import UTC

from src import futures_kraken_cli  # noqa: E402
from src.config import get_settings, reload_settings  # noqa: E402
from src.live_killswitch import (  # noqa: E402
    KillSwitchConfig,
    KillSwitchOrchestrator,
    PnLSnapshot,
)
from src.logger import get_logger, setup_logging  # noqa: E402

logger = get_logger("live_crypto_killswitch")

DEFAULT_PROFILE = "live_crypto_aggressive_capped"
DEFAULT_LOG_PATH = "data/killswitch.log"


# ---------------------------------------------------------------------------
# Pre-flight validation
# ---------------------------------------------------------------------------


class PreflightError(RuntimeError):
    """Raised when an activation pre-condition is not satisfied."""


def _validate_env_or_raise(*, required_profile: str) -> None:
    """Raise :class:`PreflightError` if any pre-condition is missing."""
    if os.environ.get("KRAKEN_ALPHA_PROFILE") != required_profile:
        raise PreflightError(
            f"KRAKEN_ALPHA_PROFILE must be set to {required_profile!r} "
            f"(got {os.environ.get('KRAKEN_ALPHA_PROFILE')!r}). Run "
            f"`$env:KRAKEN_ALPHA_PROFILE={required_profile!r}` first."
        )

    if (os.environ.get("TRADING_MODE", "").lower() != "live"):
        raise PreflightError("TRADING_MODE must be 'live' in the current shell")
    if os.environ.get("LIVE_TRADING", "").lower() != "true":
        raise PreflightError("LIVE_TRADING must be 'true' in the current shell")
    if os.environ.get("ALLOW_LIVE_ORDERS", "").lower() != "true":
        raise PreflightError("ALLOW_LIVE_ORDERS must be 'true' in the current shell")

    futures_key = (
        os.environ.get("KRAKEN_FUTURES_API_KEY")
        or os.environ.get("KRAKEN_API_KEY")
        or ""
    )
    futures_secret = (
        os.environ.get("KRAKEN_FUTURES_API_SECRET")
        or os.environ.get("KRAKEN_API_SECRET")
        or ""
    )
    if not futures_key or not futures_secret:
        raise PreflightError(
            "KRAKEN_FUTURES_API_KEY / KRAKEN_FUTURES_API_SECRET must be set "
            "in the current shell (or KRAKEN_API_KEY/SECRET as a fallback)."
        )

    reload_settings()
    settings = get_settings()
    if required_profile not in settings.available_profiles:
        raise PreflightError(
            f"profile {required_profile!r} is not declared in config.yaml. "
            "The walk-forward returned zero survivors for the crypto universe "
            "so this profile has been intentionally left out; refusing to "
            "activate. See docs/OPTION_D_ACTIVATION.md for the EV-negative "
            "verdict."
        )
    if settings.active_profile != required_profile:
        raise PreflightError(
            f"active profile is {settings.active_profile!r}, expected "
            f"{required_profile!r}"
        )

    engine = (settings.config.execution.engine or "spot").lower()
    if engine != "futures":
        raise PreflightError(
            f"profile {required_profile!r} must declare "
            "execution.engine: futures"
        )

    risk_cap = float(settings.config.risk.max_total_exposure_usd or 0.0)
    if risk_cap > 30.0 + 1e-6:
        raise PreflightError(
            f"profile {required_profile!r} has "
            f"max_total_exposure_usd={risk_cap}; option-D cap is 30.00USD"
        )


# ---------------------------------------------------------------------------
# Real PnL source backed by Kraken Futures
# ---------------------------------------------------------------------------


def _fetch_futures_accounts_pnl() -> PnLSnapshot:
    """Return the latest PnL snapshot from ``kraken futures accounts``.

    Kraken Futures' ``accounts`` endpoint returns a dict per wallet with
    ``unrealizedFunding`` / ``pnl`` blocks (exact shape varies by API
    version). We aggregate every wallet's ``unrealized`` value and use
    the running ``balance`` delta as a coarse realized signal. If the
    payload cannot be parsed the call raises so the orchestrator can
    count the failure against ``snapshot_failure_limit``.
    """

    result = futures_kraken_cli.run_futures_cli(["accounts"], timeout=15)
    if not result.ok or not isinstance(result.stdout_json, dict):
        raise RuntimeError(
            f"kraken futures accounts failed: status={result.status} "
            f"stderr={(result.stderr or '')[:200]}"
        )
    payload = result.stdout_json
    accounts = payload.get("accounts") or {}
    realized = 0.0
    unrealized = 0.0
    if isinstance(accounts, dict):
        for wallet in accounts.values():
            if not isinstance(wallet, dict):
                continue
            realized += float(wallet.get("balance") or 0.0)
            unrealized += float(wallet.get("pnl") or wallet.get("unrealizedFunding") or 0.0)
    return PnLSnapshot(
        realized_usd=realized,
        unrealized_usd=unrealized,
        at_iso=_now_iso(),
        source="kraken_futures_accounts",
        raw=payload,
    )


def _now_iso() -> str:
    from datetime import datetime

    return (
        datetime.now(UTC)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# Cancel-all + flatten callbacks (production wiring)
# ---------------------------------------------------------------------------


def _cancel_all_production() -> dict:
    """Set the dead-man's switch to 1 second so Kraken self-cancels.

    ``cancel-after 1`` is the safest way to drop *every* open order in
    a single API call: Kraken disarms only when we ping again with a
    larger value, which we never do during a kill-switch event.
    """
    result = futures_kraken_cli.cancel_after(1)
    return {
        "ok": result.ok,
        "status": result.status,
        "stdout_json": result.stdout_json,
        "stderr": result.stderr,
    }


def _flatten_positions_production() -> dict:
    """Reduce every open long to zero via ``--reduce-only`` market sells."""
    pos = futures_kraken_cli.fetch_open_positions()
    if not pos.ok or not isinstance(pos.stdout_json, dict):
        return {
            "ok": False,
            "error": f"positions fetch failed: {pos.status} {pos.stderr[:200]}",
        }
    raw_positions = pos.stdout_json.get("openPositions") or pos.stdout_json.get("positions") or []
    actions: list[dict] = []
    if isinstance(raw_positions, list):
        for entry in raw_positions:
            if not isinstance(entry, dict):
                continue
            symbol = entry.get("symbol") or entry.get("pair")
            size = float(entry.get("size") or entry.get("quantity") or 0.0)
            side = (entry.get("side") or "").lower()
            if not symbol or size <= 0 or side != "long":
                continue
            res = futures_kraken_cli.place_live_order(
                side="SELL",
                symbol=symbol,
                size=size,
                order_type="market",
                reduce_only=True,
            )
            actions.append({
                "symbol": symbol,
                "size": size,
                "ok": res.ok,
                "status": res.status,
                "stderr": res.stderr,
            })
    return {"ok": True, "actions": actions}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Option-D live crypto session supervisor with a hard -5USD "
            "kill switch. Never auto-starts; the operator must pass "
            "--i-understand-the-risks explicitly."
        )
    )
    p.add_argument(
        "--i-understand-the-risks",
        action="store_true",
        help="REQUIRED: confirms the operator read docs/OPTION_D_ACTIVATION.md",
    )
    p.add_argument(
        "--profile",
        type=str,
        default=DEFAULT_PROFILE,
        help=f"required profile name (default {DEFAULT_PROFILE})",
    )
    p.add_argument(
        "--threshold-usd",
        type=float,
        default=-5.0,
        help="kill-switch threshold in USD (default -5.0; clamped to <= -0.01)",
    )
    p.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=10.0,
        help="PnL polling interval (default 10s)",
    )
    p.add_argument(
        "--max-duration-hours",
        type=float,
        default=24.0,
        help="hard ceiling on session duration (default 24h)",
    )
    p.add_argument(
        "--flatten-cest-hour",
        type=int,
        default=21,
        help="CEST hour at which to flatten and stop (default 21)",
    )
    p.add_argument(
        "--flatten-cest-minute",
        type=int,
        default=55,
        help="CEST minute at which to flatten and stop (default 55)",
    )
    p.add_argument(
        "--log-path",
        type=str,
        default=DEFAULT_LOG_PATH,
        help=f"kill-switch event log (default {DEFAULT_LOG_PATH})",
    )
    p.add_argument(
        "--skip-subprocess",
        action="store_true",
        help=(
            "do NOT spawn scripts/run_agent_loop.py — useful for a "
            "smoke check of the supervisor itself (rarely needed)."
        ),
    )
    p.add_argument(
        "--dry-validate",
        action="store_true",
        help=(
            "run preflight only and exit; never spawns the agent loop "
            "and never queries Kraken — safe to run from any shell."
        ),
    )
    return p.parse_args()


def _spawn_agent_loop() -> subprocess.Popen:
    """Spawn ``python scripts/run_agent_loop.py`` as a child process."""
    cmd = [sys.executable, str(ROOT / "scripts" / "run_agent_loop.py")]
    logger.info("spawning agent loop subprocess: %s", " ".join(cmd))
    return subprocess.Popen(  # noqa: S603 — intentional spawn
        cmd,
        cwd=str(ROOT),
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def _terminate_subprocess(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass


def main() -> int:
    args = _parse_args()
    setup_logging()

    if not args.i_understand_the_risks:
        print(
            "REFUSED: --i-understand-the-risks is required. Read "
            "docs/OPTION_D_ACTIVATION.md first.",
            file=sys.stderr,
        )
        return 2

    try:
        _validate_env_or_raise(required_profile=args.profile)
    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr)
        return 3

    if args.dry_validate:
        print("PREFLIGHT OK — dry-validate complete, no subprocess spawned.")
        return 0

    config = KillSwitchConfig(
        threshold_usd=float(args.threshold_usd),
        poll_interval_seconds=float(args.poll_interval_seconds),
        max_duration_seconds=float(args.max_duration_hours) * 3600.0,
        flatten_cest_hour=int(args.flatten_cest_hour),
        flatten_cest_minute=int(args.flatten_cest_minute),
    )
    log_path = Path(args.log_path)
    if not log_path.is_absolute():
        log_path = (ROOT / log_path).resolve()

    agent_proc: subprocess.Popen | None = None
    if not args.skip_subprocess:
        agent_proc = _spawn_agent_loop()
        # Give the agent loop a few seconds to come up before we capture
        # the baseline snapshot.
        time.sleep(3)

    orchestrator = KillSwitchOrchestrator(
        pnl_source=_DirectPnLSource(),
        config=config,
        cancel_all=_cancel_all_production,
        flatten_positions=_flatten_positions_production,
        terminate_subprocess=lambda: _terminate_subprocess(agent_proc),
        log_path=log_path,
    )

    def _handle_sigint(*_):
        logger.info("SIGINT/SIGTERM received — requesting orchestrator stop")
        orchestrator.request_stop(reason="operator_sigint")

    signal.signal(signal.SIGINT, _handle_sigint)
    try:
        signal.signal(signal.SIGTERM, _handle_sigint)
    except (AttributeError, ValueError):
        pass  # Windows console may not expose SIGTERM

    orchestrator.start_session()
    exit_code = orchestrator.run()
    return exit_code


class _DirectPnLSource:
    """Thin wrapper so :class:`KillSwitchOrchestrator` can call ``.snapshot()``."""

    def snapshot(self) -> PnLSnapshot:
        return _fetch_futures_accounts_pnl()


if __name__ == "__main__":
    raise SystemExit(main())
