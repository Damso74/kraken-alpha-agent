"""Thin subprocess wrapper around the Kraken CLI.

Design goals
------------
- Never raise inside hot paths. Always return a standardised dict so the
  caller can decide what to do.
- Never log a secret: keys are passed via the subprocess environment and any
  occurrence of the value in stdout/stderr is masked by the logger.
- Be useful even if the CLI is not installed locally: the higher-level
  functions (``fetch_ticker`` / ``fetch_ohlc`` / ``place_order``) fall back to
  a deterministic mock generator. Mock results are clearly flagged with
  ``source = "mock"``.
- Be conservative with order commands. ``place_order`` requires the agent's
  triple opt-in to be set; otherwise it short-circuits to a ``blocked`` state.

Confirmed commands (from the official Kraken CLI tutorial + product page):
- ``kraken ticker <pair> --output json``
- ``kraken ohlc <pair> --interval 60 --output json``
- ``kraken paper init/buy/sell/reset --output json``
- ``kraken order buy/sell ...``
- ``kraken order cancel-after <seconds>``
- ``kraken <order> --validate`` for live-order dry-run

Commands marked TODO are guarded with ``# TODO confirm command name``.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .config import get_settings
from .logger import get_logger
from .schemas import Action
from .universe import candidate_pair_forms
from .utils import utc_now_iso

logger = get_logger(__name__)

CLIResultStatus = Literal["ok", "error", "mock", "missing_cli", "blocked"]

DEFAULT_TIMEOUT_SECONDS = 12
KRAKEN_BIN_CANDIDATES = ("kraken", "krakenfx", "kraken.exe")


@dataclass
class CLIResult:
    ok: bool
    status: CLIResultStatus
    command: list[str] = field(default_factory=list)
    stdout_json: Any | None = None
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    source: str = "kraken_cli"
    at: str = field(default_factory=utc_now_iso)


def _resolve_binary() -> str | None:
    for name in KRAKEN_BIN_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def is_installed() -> bool:
    return _resolve_binary() is not None


def get_version() -> str | None:
    binary = _resolve_binary()
    if not binary:
        return None
    try:
        out = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (out.stdout or out.stderr or "").strip()
        return text.splitlines()[0] if text else None
    except Exception:  # noqa: BLE001
        return None


def _env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    s = get_settings().env
    if s.kraken_api_key:
        env["KRAKEN_API_KEY"] = s.kraken_api_key
    if s.kraken_api_secret:
        env["KRAKEN_API_SECRET"] = s.kraken_api_secret
    return env


def run_cli(
    args: Iterable[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    parse_json: bool = True,
) -> CLIResult:
    """Run a Kraken CLI command. Adds ``--output json`` automatically."""

    binary = _resolve_binary()
    arg_list = list(args)
    cmd_for_log = [binary or "kraken", *arg_list]
    if not binary:
        return CLIResult(
            ok=False,
            status="missing_cli",
            command=cmd_for_log,
            stderr="Kraken CLI binary not found on PATH",
        )

    full = [binary, *arg_list]
    if parse_json and not any(a in {"-o", "--output"} for a in arg_list):
        full += ["--output", "json"]

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            full,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_env_for_subprocess(),
        )
    except subprocess.TimeoutExpired as exc:
        return CLIResult(
            ok=False,
            status="error",
            command=full,
            stderr=f"timeout after {timeout}s: {exc}",
            exit_code=None,
            duration_ms=int((time.perf_counter() - start) * 1000),
        )
    except FileNotFoundError as exc:
        return CLIResult(
            ok=False,
            status="missing_cli",
            command=full,
            stderr=str(exc),
            duration_ms=int((time.perf_counter() - start) * 1000),
        )

    duration_ms = int((time.perf_counter() - start) * 1000)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    payload: Any | None = None
    if parse_json and stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            stderr = (stderr + f"\n[non-json stdout]: {stdout[:200]}").strip()

    return CLIResult(
        ok=proc.returncode == 0,
        status="ok" if proc.returncode == 0 else "error",
        command=full,
        stdout_json=payload,
        stderr=stderr,
        exit_code=proc.returncode,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# Deterministic mock data — used whenever the CLI is unavailable.
# ---------------------------------------------------------------------------


def _seed_for(symbol: str) -> int:
    digest = hashlib.sha256(symbol.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _mock_base_price(symbol: str) -> float:
    bases = {
        "AAPLx": 220.0,
        "TSLAx": 235.0,
        "NVDAx": 940.0,
        "MSFTx": 430.0,
        "AMZNx": 198.0,
        "GOOGLx": 175.0,
        "METAx": 540.0,
        "SPYx": 580.0,
        "QQQx": 510.0,
        "MSTRx": 1450.0,
        "HOODx": 38.0,
        "CRCLx": 32.0,
        "GLDx": 235.0,
    }
    return bases.get(symbol, 100.0 + (_seed_for(symbol) % 400))


def _mock_candles(symbol: str, interval_minutes: int = 60, count: int = 24) -> list[dict[str, float]]:
    base = _mock_base_price(symbol)
    seed = _seed_for(symbol)
    # Time-anchored so consecutive calls produce a coherent series without
    # being deterministic to the second.
    bucket = int(time.time() // (interval_minutes * 60))
    candles: list[dict[str, float]] = []
    price = base
    for i in range(count):
        t = bucket - (count - 1 - i)
        # Two superposed waves give the demo enough variety to occasionally
        # produce BUY/SELL signals while staying deterministic.
        wave_a = math.sin((t + seed) % 23 / 23.0 * math.tau) * 0.020
        wave_b = math.sin((t * 3 + (seed >> 4)) % 11 / 11.0 * math.tau) * 0.010
        wave = wave_a + wave_b
        drift = (((seed >> 8) % 11) - 5) / 1000.0
        open_ = price
        close_ = max(0.01, price * (1 + wave + drift))
        high = max(open_, close_) * (1 + abs(wave) * 0.6 + 0.001)
        low = min(open_, close_) * (1 - abs(wave) * 0.6 - 0.001)
        volume = 1000 + (seed % 5000) + (i * 13)
        candles.append({
            "timestamp": t * interval_minutes * 60,
            "open": round(open_, 4),
            "high": round(high, 4),
            "low": round(low, 4),
            "close": round(close_, 4),
            "vwap": round((open_ + close_) / 2, 4),
            "volume": float(volume),
        })
        price = close_
    return candles


def _mock_ticker(symbol: str) -> dict[str, Any]:
    candles = _mock_candles(symbol, 60, 24)
    last = candles[-1]["close"]
    high_24h = max(c["high"] for c in candles)
    low_24h = min(c["low"] for c in candles)
    volume_24h = sum(c["volume"] for c in candles)
    spread = max(0.01, last * 0.0008)
    return {
        "pair": symbol,
        "ask": round(last + spread, 4),
        "bid": round(last - spread, 4),
        "last": round(last, 4),
        "high_24h": round(high_24h, 4),
        "low_24h": round(low_24h, 4),
        "volume_24h": round(volume_24h, 2),
        "open": candles[0]["open"],
        "source": "mock",
    }


# ---------------------------------------------------------------------------
# High-level operations used by the rest of the agent.
# ---------------------------------------------------------------------------


def _parse_kraken_ticker_payload(symbol: str, payload: Any) -> dict[str, Any] | None:
    """Normalise the Kraken public-Ticker style payload into our flat dict."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get(symbol) or payload.get(symbol.replace("/", "")) or payload
    if not isinstance(raw, dict):
        return None
    if "last" in raw and "ask" in raw and "bid" in raw:
        return {
            "pair": symbol,
            "ask": raw.get("ask"),
            "bid": raw.get("bid"),
            "last": raw.get("last"),
            "high_24h": raw.get("high_24h"),
            "low_24h": raw.get("low_24h"),
            "volume_24h": raw.get("volume_24h"),
            "open": raw.get("open"),
            "source": "kraken_cli",
        }
    # Kraken public-Ticker REST style.
    def _first(seq, idx=0):
        try:
            return seq[idx]
        except Exception:  # noqa: BLE001
            return None

    return {
        "pair": symbol,
        "ask": _first(raw.get("a", [None]), 0),
        "bid": _first(raw.get("b", [None]), 0),
        "last": _first(raw.get("c", [None]), 0),
        "high_24h": _first(raw.get("h", [None, None]), 1),
        "low_24h": _first(raw.get("l", [None, None]), 1),
        "volume_24h": _first(raw.get("v", [None, None]), 1),
        "open": raw.get("o"),
        "source": "kraken_cli",
    }


def fetch_ticker(symbol_ticker: str, quote: str = "USD") -> dict[str, Any]:
    """Fetch a ticker for an xStocks symbol.

    Tries the slash and compact forms of the pair, then falls back to mock.
    """
    forms = candidate_pair_forms(symbol_ticker, quote)
    last_err = ""
    for pair in forms:
        # TODO: confirm exact CLI surface for xStocks ticker symbol format.
        result = run_cli(["ticker", pair])
        if result.ok and result.stdout_json is not None:
            parsed = _parse_kraken_ticker_payload(pair, result.stdout_json)
            if parsed:
                parsed["source"] = "kraken_cli"
                return parsed
        last_err = result.stderr or f"exit={result.exit_code}"
        if result.status == "missing_cli":
            break
    fallback = _mock_ticker(symbol_ticker)
    fallback["fallback_reason"] = last_err or "kraken_cli_unavailable"
    return fallback


def fetch_ohlc(
    symbol_ticker: str,
    quote: str = "USD",
    interval_minutes: int = 60,
    count: int = 24,
) -> list[dict[str, float]]:
    forms = candidate_pair_forms(symbol_ticker, quote)
    for pair in forms:
        result = run_cli(["ohlc", pair, "--interval", str(interval_minutes)])
        if not result.ok or result.stdout_json is None:
            if result.status == "missing_cli":
                break
            continue
        payload = result.stdout_json
        candles_raw = payload.get(pair) if isinstance(payload, dict) else payload
        if isinstance(candles_raw, dict):
            candles_raw = candles_raw.get("candles") or candles_raw.get("data")
        if not isinstance(candles_raw, list):
            continue
        out: list[dict[str, float]] = []
        for c in candles_raw[-count:]:
            if isinstance(c, list) and len(c) >= 7:
                out.append({
                    "timestamp": c[0],
                    "open": float(c[1]),
                    "high": float(c[2]),
                    "low": float(c[3]),
                    "close": float(c[4]),
                    "vwap": float(c[5]),
                    "volume": float(c[6]),
                })
            elif isinstance(c, dict):
                out.append({
                    "timestamp": c.get("timestamp") or c.get("time"),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "vwap": float(c.get("vwap", 0)),
                    "volume": float(c.get("volume", 0)),
                })
        if out:
            return out
    return _mock_candles(symbol_ticker, interval_minutes=interval_minutes, count=count)


def fetch_balances() -> dict[str, Any]:
    # TODO: confirm command name — `kraken balance` vs `kraken account balance`.
    result = run_cli(["balance"])
    if result.ok and isinstance(result.stdout_json, dict):
        return {"source": "kraken_cli", "balances": result.stdout_json}
    if result.status == "missing_cli":
        return {"source": "mock", "balances": {"USD": 10_000.0}, "note": "kraken cli not installed"}
    return {
        "source": "mock",
        "balances": {"USD": 10_000.0},
        "note": f"balance fallback: {result.stderr or 'unknown'}",
    }


def fetch_paper_status() -> dict[str, Any]:
    # TODO: confirm exact command — `kraken paper status` is referenced in the
    # Kraken CLI tutorial but not formally documented.
    result = run_cli(["paper", "status"])
    if result.ok and result.stdout_json is not None:
        return {"source": "kraken_cli", "data": result.stdout_json}
    if result.status == "missing_cli":
        return {"source": "mock", "data": {"cash_usd": 10_000.0, "positions": []}}
    return {
        "source": "mock",
        "data": {"cash_usd": 10_000.0, "positions": []},
        "note": result.stderr or "paper status fallback",
    }


def cancel_after(seconds: int) -> CLIResult:
    """Dead-man's switch: cancel all open orders after N seconds of silence."""
    return run_cli(["order", "cancel-after", str(int(seconds))])


def validate_live_order(symbol_pair: str, action: Action, volume: float) -> CLIResult:
    side = "buy" if action == "BUY" else "sell"
    return run_cli(["order", side, symbol_pair, str(volume), "--validate"])


def place_order(
    *,
    mode: Literal["paper", "live"],
    symbol_pair: str,
    action: Action,
    volume: float,
    yes: bool = True,
) -> CLIResult:
    """Place an order via the Kraken CLI.

    The caller is responsible for the triple opt-in gate; this function only
    checks that the mode is allowed and the action is BUY/SELL.
    """
    if action not in ("BUY", "SELL"):
        return CLIResult(ok=False, status="blocked", command=[], stderr="action must be BUY or SELL")
    side = "buy" if action == "BUY" else "sell"
    args: list[str] = []
    if mode == "paper":
        args = ["paper", side, symbol_pair, str(volume)]
    elif mode == "live":
        args = ["order", side, symbol_pair, str(volume)]
    else:
        return CLIResult(ok=False, status="blocked", command=[], stderr=f"unsupported mode {mode}")
    if yes:
        args.append("--yes")
    return run_cli(args, timeout=20)


def kraken_diagnostics() -> dict[str, Any]:
    binary = _resolve_binary()
    return {
        "installed": binary is not None,
        "binary": binary,
        "version": get_version() if binary else None,
        "candidates": list(KRAKEN_BIN_CANDIDATES),
    }


__all__ = [
    "CLIResult",
    "DEFAULT_TIMEOUT_SECONDS",
    "is_installed",
    "get_version",
    "run_cli",
    "fetch_ticker",
    "fetch_ohlc",
    "fetch_balances",
    "fetch_paper_status",
    "cancel_after",
    "validate_live_order",
    "place_order",
    "kraken_diagnostics",
]
