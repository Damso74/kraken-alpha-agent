"""Live-mode preflight checklist.

The script reads-only — it never sends an order. Run it before flipping
the triple opt-in on a VPS. Every check prints a clear PASS/FAIL line
and the exit code reflects the worst result so it composes with CI.

Checks performed:
1. ``KRAKEN_API_KEY`` and ``KRAKEN_API_SECRET`` are populated (presence
   only — never displayed).
2. Active profile is ``micro_live_100eur``.
3. ``TRADING_MODE`` is NOT ``live`` (unless ``--allow-live-env-check``).
4. ``LIVE_TRADING`` / ``ALLOW_LIVE_ORDERS`` are not accidentally ``true``.
5. ``data/validate_live_xstocks_latest.json`` exists and contains at
   least one OK symbol.
6. Profile ``micro_live_100eur`` is defined and shape is sane
   (shorting disabled, max_total_exposure_usd ≤ 30,
   max_position_notional_usd ≤ 10).
7. ``LOW_LIQUIDITY`` is still in ``risk.block_if_regime``.
8. ``src.exit_rules`` imports cleanly.
9. Withdrawal permission cannot be checked from code → reminder line.
10. Recommended tests are listed.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


VALIDATE_LATEST = ROOT / "data" / "validate_live_xstocks_latest.json"
VALIDATE_PERPS_LATEST = ROOT / "data" / "validate_live_xstocks_perps_latest.json"
TARGET_PROFILE = "micro_live_100eur"
MAX_EXPOSURE = 30.0
MAX_POSITION = 10.0
HARDCODED_MAX_LEVERAGE = 1.0


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    fatal: bool = True


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in ("1", "true", "yes", "on")


def _load_settings():
    """Import fresh settings — caches must be cleared because env may have changed."""
    from src import config as cfg

    cfg.get_settings.cache_clear()
    return cfg.get_settings()


def _check_api_keys() -> Check:
    key = os.environ.get("KRAKEN_API_KEY") or ""
    secret = os.environ.get("KRAKEN_API_SECRET") or ""
    return Check(
        name="api_keys_present",
        passed=bool(key) and bool(secret),
        detail=(
            f"KRAKEN_API_KEY set={bool(key)} secret set={bool(secret)} "
            "(values never printed)"
        ),
    )


def _check_futures_api_keys(engine: str) -> Check:
    """When engine=futures, the dedicated Futures keys must be populated.

    Falls back to the spot keys (KRAKEN_API_KEY / SECRET) for environments
    that share credentials, but the dedicated KRAKEN_FUTURES_API_KEY /
    KRAKEN_FUTURES_API_SECRET pair is strongly recommended on Kraken
    Futures because the venue is separate from spot.
    """
    if engine != "futures":
        return Check(
            name="futures_keys_present",
            passed=True,
            detail=f"engine={engine!r} (futures key check skipped)",
            fatal=False,
        )
    fkey = os.environ.get("KRAKEN_FUTURES_API_KEY") or ""
    fsec = os.environ.get("KRAKEN_FUTURES_API_SECRET") or ""
    skey = os.environ.get("KRAKEN_API_KEY") or ""
    ssec = os.environ.get("KRAKEN_API_SECRET") or ""
    have_dedicated = bool(fkey) and bool(fsec)
    have_fallback = bool(skey) and bool(ssec)
    return Check(
        name="futures_keys_present",
        passed=have_dedicated or have_fallback,
        detail=(
            f"KRAKEN_FUTURES_API_KEY set={bool(fkey)} secret set={bool(fsec)} "
            f"(fallback to KRAKEN_API_* set={have_fallback}; values never printed)"
        ),
    )


def _check_active_profile(settings) -> Check:
    return Check(
        name="active_profile",
        passed=settings.active_profile == TARGET_PROFILE,
        detail=f"active={settings.active_profile!r} expected={TARGET_PROFILE!r}",
    )


def _check_trading_mode(allow_live_env_check: bool) -> Check:
    mode = (os.environ.get("TRADING_MODE") or "dry_run").lower()
    if allow_live_env_check:
        return Check(
            name="trading_mode_env",
            passed=True,
            detail=f"mode={mode} (live-env check allowed by --allow-live-env-check)",
            fatal=False,
        )
    return Check(
        name="trading_mode_not_live",
        passed=mode != "live",
        detail=f"TRADING_MODE={mode!r} (preflight should be run with dry_run)",
    )


def _check_live_flags_off() -> Check:
    lt = _truthy(os.environ.get("LIVE_TRADING"))
    al = _truthy(os.environ.get("ALLOW_LIVE_ORDERS"))
    return Check(
        name="live_flags_off_at_preflight",
        passed=not lt and not al,
        detail=(
            f"LIVE_TRADING={lt} ALLOW_LIVE_ORDERS={al} "
            "(both must be false during preflight; flip ON only after this script passes)"
        ),
        fatal=False,
    )


def _check_validate_latest_for_engine(engine: str) -> Check:
    """Pick the right validate artefact for the active engine.

    * engine=spot → data/validate_live_xstocks_latest.json (legacy)
    * engine=futures → data/validate_live_xstocks_perps_latest.json
    """
    target = VALIDATE_PERPS_LATEST if engine == "futures" else VALIDATE_LATEST
    script_hint = (
        "scripts/validate_live_xstocks_perps.py"
        if engine == "futures"
        else "scripts/validate_live_xstocks.py"
    )
    name = (
        "validate_perps_latest_has_ok_symbol"
        if engine == "futures"
        else "validate_latest_has_ok_symbol"
    )
    if not target.exists():
        return Check(
            name=name,
            passed=False,
            detail=(
                f"{target} missing — run `python {script_hint}` first"
            ),
        )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return Check(
            name=name,
            passed=False,
            detail=f"could not parse {target}: {exc}",
        )
    results = payload.get("results") or []
    ok_syms = [r.get("symbol") for r in results if r.get("ok")]
    return Check(
        name=name,
        passed=len(ok_syms) >= 1,
        detail=(
            f"engine={engine} ok_symbols={ok_syms or 'none'} "
            f"(need >=1; rerun {script_hint} if everything is FAIL)"
        ),
    )


def _check_futures_engine_runtime(settings) -> list[Check]:
    """Engine-level checks. Only run when the active profile selects futures.

    Ensures:
    * ``execution.engine == "futures"`` on the active profile.
    * ``futures.max_leverage`` is exactly ``HARDCODED_MAX_LEVERAGE`` (1.0).
    * ``futures.max_funding_rate_pct_per_hour`` is set (>0, finite).
    * The risk-gate exposes a ``max_leverage`` constant equal to the cap so
      a config drift cannot relax the safeguard silently.
    """
    cfg = settings.config
    engine = (cfg.execution.engine or "spot").lower()
    if engine != "futures":
        return [
            Check(
                name="futures_engine_active",
                passed=settings.active_profile != TARGET_PROFILE,
                detail=(
                    f"engine={engine!r} (futures-engine checks skipped; "
                    f"micro_live_100eur expects engine=futures)"
                ),
                fatal=(settings.active_profile == TARGET_PROFILE),
            )
        ]
    fcfg = getattr(cfg, "futures", None)
    max_lev = float(getattr(fcfg, "max_leverage", 0.0) or 0.0)
    funding_cap = float(getattr(fcfg, "max_funding_rate_pct_per_hour", 0.0) or 0.0)
    try:
        from src.risk import HARDCODED_MAX_LEVERAGE as RISK_CAP
    except Exception as exc:  # noqa: BLE001
        return [
            Check(
                name="futures_engine_imports_risk_cap",
                passed=False,
                detail=f"could not read risk.HARDCODED_MAX_LEVERAGE: {exc}",
            )
        ]
    return [
        Check(
            name="futures_engine_active",
            passed=True,
            detail="execution.engine=futures (Kraken Futures Perpetual xStocks @ 1x)",
        ),
        Check(
            name="max_leverage_eq_1",
            passed=abs(max_lev - HARDCODED_MAX_LEVERAGE) < 1e-9
            and abs(RISK_CAP - HARDCODED_MAX_LEVERAGE) < 1e-9,
            detail=(
                f"futures.max_leverage={max_lev} risk.HARDCODED_MAX_LEVERAGE={RISK_CAP} "
                f"expected={HARDCODED_MAX_LEVERAGE}"
            ),
        ),
        Check(
            name="funding_rate_threshold_set",
            passed=funding_cap > 0.0 and funding_cap <= 5.0,
            detail=(
                f"futures.max_funding_rate_pct_per_hour={funding_cap}%/h "
                "(expected: > 0 and <= 5%/h for sanity)"
            ),
        ),
    ]


def _check_profile_defined_and_safe(settings) -> list[Check]:
    profile = TARGET_PROFILE
    checks: list[Check] = []
    available = list(settings.available_profiles or [])
    checks.append(
        Check(
            name="micro_live_profile_defined",
            passed=profile in available,
            detail=f"available={available}",
        )
    )

    cfg = settings.config
    # The active profile is what governs runtime; only assert structural
    # constraints when micro_live_100eur is actually active (otherwise we
    # only know it exists in YAML, not the merged values).
    if settings.active_profile == profile:
        checks.append(
            Check(
                name="shorting_disabled",
                passed=cfg.trading.shorting_enabled is False,
                detail=f"trading.shorting_enabled={cfg.trading.shorting_enabled}",
            )
        )
        checks.append(
            Check(
                name="max_total_exposure_usd_<=_30",
                passed=cfg.risk.max_total_exposure_usd <= MAX_EXPOSURE,
                detail=f"max_total_exposure_usd={cfg.risk.max_total_exposure_usd}",
            )
        )
        checks.append(
            Check(
                name="max_position_notional_usd_<=_10",
                passed=cfg.risk.max_position_notional_usd <= MAX_POSITION,
                detail=f"max_position_notional_usd={cfg.risk.max_position_notional_usd}",
            )
        )
    return checks


def _check_low_liquidity_gate(settings) -> Check:
    gates = list(settings.config.risk.block_if_regime or [])
    return Check(
        name="low_liquidity_runtime_gate",
        passed="LOW_LIQUIDITY" in gates,
        detail=f"risk.block_if_regime={gates}",
    )


def _check_exit_rules_imports() -> Check:
    try:
        mod = importlib.import_module("src.exit_rules")
        for fn in ("evaluate_exit_rules", "stop_loss_exit", "take_profit_exit",
                   "momentum_exit", "time_exit", "flatten_before_close_exit"):
            getattr(mod, fn)
    except Exception as exc:  # noqa: BLE001
        return Check(name="exit_rules_imports", passed=False, detail=str(exc))
    return Check(name="exit_rules_imports", passed=True, detail="ok")


def _print_check(check: Check) -> None:
    tag = "PASS" if check.passed else ("FAIL" if check.fatal else "WARN")
    print(f"[{tag}] {check.name}: {check.detail}")


def _run(allow_live_env_check: bool) -> int:
    print("=== Kraken Alpha Agent — live preflight ===")
    print("(read-only; no order is sent)")
    print("")

    checks: list[Check] = []
    settings = _load_settings()
    engine = (settings.config.execution.engine or "spot").lower()

    checks.append(_check_api_keys())
    checks.append(_check_futures_api_keys(engine))
    checks.append(_check_active_profile(settings))
    checks.append(_check_trading_mode(allow_live_env_check))
    checks.append(_check_live_flags_off())
    checks.append(_check_validate_latest_for_engine(engine))
    checks.extend(_check_profile_defined_and_safe(settings))
    checks.append(_check_low_liquidity_gate(settings))
    checks.append(_check_exit_rules_imports())
    checks.extend(_check_futures_engine_runtime(settings))

    for c in checks:
        _print_check(c)

    print("")
    print("Reminders (cannot be verified by code):")
    print(" - The Kraken API key MUST NOT have withdrawal permission.")
    print(" - Max exposure ceiling on this account is 30 USD/EUR.")
    print(" - Stop trading by end of Friday (US session) before weekend.")
    print(" - Recommended tests before flipping live:")
    print("     python -m pytest --tb=short")
    print("     python scripts/dry_run_once.py")
    print("     python scripts/backtest_xstocks.py --top 8 --profile aggressive_competition --market-hours-report")
    print("     python scripts/validate_live_xstocks.py        # spot engine")
    print("     python scripts/validate_live_xstocks_perps.py  # futures engine (micro_live_100eur)")

    fatal_failures = [c for c in checks if not c.passed and c.fatal]
    if fatal_failures:
        print("")
        print(f"PREFLIGHT FAILED — {len(fatal_failures)} blocking check(s).")
        return 1
    print("")
    print("PREFLIGHT PASSED — review reminders above before flipping the triple opt-in.")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Live-mode preflight checklist (read-only).")
    p.add_argument(
        "--allow-live-env-check",
        action="store_true",
        help=(
            "Skip the TRADING_MODE!=live assertion. Use only when running "
            "the preflight from a VPS where TRADING_MODE is intentionally "
            "already set to live."
        ),
    )
    args = p.parse_args(argv)
    return _run(allow_live_env_check=args.allow_live_env_check)


if __name__ == "__main__":
    raise SystemExit(main())
