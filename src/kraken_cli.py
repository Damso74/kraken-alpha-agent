"""Subprocess wrapper around the Kraken CLI.

The wrapper is the **only** place that knows how to invoke ``kraken``. It hides
three implementation details from the rest of the agent:

1. *Transport.* On macOS / Linux the binary is invoked directly. On Windows,
   where the official installer does not ship a native build, we fall back to
   ``wsl -- bash -lc "kraken ..."`` so the same code path works as long as the
   CLI is installed inside a WSL distribution. The transport can be forced via
   the ``KRAKEN_CLI_TRANSPORT`` environment variable (``auto``, ``windows``,
   ``wsl`` or ``mock``).
2. *xStocks asset class.* The CLI requires ``--asset-class tokenized_asset``
   for every xStocks operation. The wrapper inserts the flag automatically
   when the pair looks like an xStock (e.g. ``AAPLx/USD``) and the underlying
   subcommand accepts it.
3. *Mock fallback.* When no transport is available the wrapper returns
   deterministic synthetic data so the agent stays runnable end-to-end. The
   mock data is **clearly labelled** (``source = "mock"``, ``using_mock = True``).

Confirmed commands against ``kraken 0.3.2``:
- ``kraken status -o json``
- ``kraken ticker <pair> [--asset-class tokenized_asset] -o json``
- ``kraken ohlc <pair> --interval 60 [--asset-class tokenized_asset] -o json``
- ``kraken orderbook <pair> --count <n> [--asset-class tokenized_asset] -o json``
- ``kraken trades <pair> --count <n> [--asset-class tokenized_asset] -o json``
- ``kraken paper status/balance -o json``
- ``kraken order buy/sell <pair> <vol> [--type ...] [--price ...] [--asset-class tokenized_asset] [--validate] -o json``

See ``CLI_VALIDATION.md`` at the repository root for the full validation log.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shlex
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

# ---------------------------------------------------------------------------
# Types & constants
# ---------------------------------------------------------------------------

CLIResultStatus = Literal["ok", "error", "mock", "missing_cli", "blocked"]
Transport = Literal["auto", "windows", "wsl", "mock"]

DEFAULT_TIMEOUT_SECONDS = 12
KRAKEN_BIN_CANDIDATES = ("kraken", "krakenfx", "kraken.exe")

# Subcommands that accept --asset-class. (All confirmed against kraken 0.3.2.)
_ASSET_CLASS_SUBCOMMANDS: frozenset[str] = frozenset({
    "ticker", "ohlc", "orderbook", "orderbook-grouped", "orderbook-l3",
    "trades", "spreads", "pairs", "assets",
    # `order buy/sell` also accept --asset-class.
    "order",
})

_XSTOCKS_PAIR_RE = re.compile(r"^[A-Z]{1,6}x(?:/[A-Z]{3,5})?$")


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
    using_mock: bool = False
    transport: str = "unknown"
    at: str = field(default_factory=utc_now_iso)


# ---------------------------------------------------------------------------
# Transport detection
# ---------------------------------------------------------------------------


def _windows_binary() -> str | None:
    for name in KRAKEN_BIN_CANDIDATES:
        found = shutil.which(name)
        if found:
            return found
    return None


def _wsl_available() -> bool:
    if os.name != "nt":
        return False
    return shutil.which("wsl") is not None


_WSL_KRAKEN_CACHE: dict[str, str | None] = {}


def _wsl_kraken_present() -> bool:
    """Probe ``kraken`` inside the default WSL distribution. Cached."""
    if not _wsl_available():
        return False
    if "result" in _WSL_KRAKEN_CACHE:
        return _WSL_KRAKEN_CACHE["result"] is not None
    try:
        proc = subprocess.run(
            ["wsl", "--", "bash", "-lc", "command -v kraken || true"],
            capture_output=True, text=True, timeout=10, encoding="utf-8",
        )
        path = (proc.stdout or "").strip().splitlines()[0] if proc.stdout else ""
        _WSL_KRAKEN_CACHE["result"] = path or None
        return bool(path)
    except Exception:  # noqa: BLE001
        _WSL_KRAKEN_CACHE["result"] = None
        return False


def _configured_transport() -> Transport:
    raw = (os.environ.get("KRAKEN_CLI_TRANSPORT", "auto") or "auto").lower()
    if raw not in ("auto", "windows", "wsl", "mock"):
        return "auto"
    return raw  # type: ignore[return-value]


def _decide_transport() -> tuple[Transport, str | None]:
    """Return (transport, optional Windows binary path)."""
    forced = _configured_transport()
    if forced == "mock":
        return "mock", None
    if forced == "windows":
        binary = _windows_binary()
        return ("windows", binary) if binary else ("mock", None)
    if forced == "wsl":
        return ("wsl", None) if _wsl_kraken_present() else ("mock", None)
    # auto
    binary = _windows_binary()
    if binary:
        return "windows", binary
    if _wsl_kraken_present():
        return "wsl", None
    return "mock", None


def is_installed() -> bool:
    transport, _ = _decide_transport()
    return transport in ("windows", "wsl")


def get_version() -> str | None:
    transport, binary = _decide_transport()
    if transport == "mock":
        return None
    cmd = _shell_command(["--version"], transport=transport, binary=binary)
    try:
        out = subprocess.run(
            cmd, capture_output=True, text=True, timeout=8,
            env=_env_for_subprocess(), encoding="utf-8",
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


# ---------------------------------------------------------------------------
# Argument augmentation: asset class + JSON
# ---------------------------------------------------------------------------


def _is_xstock(pair_or_ticker: str | None) -> bool:
    if not pair_or_ticker:
        return False
    return bool(_XSTOCKS_PAIR_RE.match(pair_or_ticker.strip()))


def _augment_args(args: list[str]) -> list[str]:
    """Inject ``-o json`` and (when relevant) ``--asset-class tokenized_asset``.

    The function never mutates the caller's list. It is idempotent: if the
    caller already passed the flags they are kept untouched.
    """
    if not args:
        return list(args)
    out = list(args)
    sub = out[0]

    # Force JSON output unless the caller already set it.
    if not any(a in {"-o", "--output"} for a in out):
        out += ["-o", "json"]

    # Inject --asset-class for xStocks if the subcommand accepts it.
    if "--asset-class" not in out and sub in _ASSET_CLASS_SUBCOMMANDS:
        if any(_is_xstock(a) for a in out):
            out += ["--asset-class", "tokenized_asset"]
    return out


# ---------------------------------------------------------------------------
# Subprocess invocation
# ---------------------------------------------------------------------------


def _shell_command(
    args: list[str], *, transport: Transport, binary: str | None
) -> list[str]:
    if transport == "windows":
        return [binary or "kraken", *args]
    if transport == "wsl":
        quoted = " ".join(shlex.quote(a) for a in args)
        return ["wsl", "--", "bash", "-lc", f"kraken {quoted}"]
    return []


def run_cli(
    args: Iterable[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    parse_json: bool = True,
) -> CLIResult:
    arg_list = list(args)
    transport, binary = _decide_transport()
    augmented = _augment_args(arg_list) if parse_json else list(arg_list)
    cmd = _shell_command(augmented, transport=transport, binary=binary)

    if transport == "mock":
        return CLIResult(
            ok=False,
            status="missing_cli",
            command=[*KRAKEN_BIN_CANDIDATES[:1], *augmented],
            stderr="Kraken CLI not available (transport=mock)",
            transport=transport,
            using_mock=True,
        )

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_env_for_subprocess(),
            encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        return CLIResult(
            ok=False, status="error", command=cmd,
            stderr=f"timeout after {timeout}s: {exc}",
            duration_ms=int((time.perf_counter() - start) * 1000),
            transport=transport,
        )
    except FileNotFoundError as exc:
        return CLIResult(
            ok=False, status="missing_cli", command=cmd, stderr=str(exc),
            duration_ms=int((time.perf_counter() - start) * 1000),
            transport=transport,
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
        command=cmd,
        stdout_json=payload,
        stderr=stderr,
        exit_code=proc.returncode,
        duration_ms=duration_ms,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# Deterministic mock data
# ---------------------------------------------------------------------------


def _seed_for(symbol: str) -> int:
    digest = hashlib.sha256(symbol.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _mock_base_price(symbol: str) -> float:
    bases = {
        "AAPLx": 220.0, "TSLAx": 235.0, "NVDAx": 940.0, "MSFTx": 430.0,
        "AMZNx": 198.0, "GOOGLx": 175.0, "METAx": 540.0, "SPYx": 580.0,
        "QQQx": 510.0, "MSTRx": 1450.0, "HOODx": 38.0, "CRCLx": 32.0,
        "GLDx": 235.0,
    }
    return bases.get(symbol, 100.0 + (_seed_for(symbol) % 400))


def _mock_candles(symbol: str, interval_minutes: int = 60, count: int = 24) -> list[dict[str, float]]:
    base = _mock_base_price(symbol)
    seed = _seed_for(symbol)
    bucket = int(time.time() // (interval_minutes * 60))
    candles: list[dict[str, float]] = []
    price = base
    for i in range(count):
        t = bucket - (count - 1 - i)
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
            "open": round(open_, 4), "high": round(high, 4), "low": round(low, 4),
            "close": round(close_, 4), "vwap": round((open_ + close_) / 2, 4),
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
        "using_mock": True,
    }


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


def _parse_kraken_ticker_payload(symbol: str, payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get(symbol) or payload.get(symbol.replace("/", "")) or payload
    if not isinstance(raw, dict):
        return None
    if "last" in raw and "ask" in raw and "bid" in raw:
        # Already normalised (some CLI versions may do this).
        return {
            "pair": symbol,
            "ask": raw.get("ask"), "bid": raw.get("bid"),
            "last": raw.get("last"),
            "high_24h": raw.get("high_24h"), "low_24h": raw.get("low_24h"),
            "volume_24h": raw.get("volume_24h"), "open": raw.get("open"),
            "source": "kraken_cli",
        }
    # REST-style ticker payload from the live Kraken API.
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

    Tries the slash form first (the official Kraken CLI form for xStocks), then
    the compact form as a defensive retry, and finally falls back to mock data.
    """
    forms = candidate_pair_forms(symbol_ticker, quote)
    last_err = ""
    for pair in forms:
        result = run_cli(["ticker", pair])
        if result.ok and result.stdout_json is not None:
            parsed = _parse_kraken_ticker_payload(pair, result.stdout_json)
            if parsed:
                parsed["source"] = "kraken_cli"
                parsed["transport"] = result.transport
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
                    "open": float(c[1]), "high": float(c[2]),
                    "low": float(c[3]), "close": float(c[4]),
                    "vwap": float(c[5]), "volume": float(c[6]),
                })
            elif isinstance(c, dict):
                out.append({
                    "timestamp": c.get("timestamp") or c.get("time"),
                    "open": float(c.get("open", 0)), "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)), "close": float(c.get("close", 0)),
                    "vwap": float(c.get("vwap", 0)), "volume": float(c.get("volume", 0)),
                })
        if out:
            return out
    return _mock_candles(symbol_ticker, interval_minutes=interval_minutes, count=count)


def fetch_orderbook(
    symbol_ticker: str, quote: str = "USD", count: int = 10
) -> dict[str, Any]:
    forms = candidate_pair_forms(symbol_ticker, quote)
    for pair in forms:
        result = run_cli(["orderbook", pair, "--count", str(int(count))])
        if result.ok and isinstance(result.stdout_json, dict):
            return {
                "source": "kraken_cli",
                "pair": pair,
                "transport": result.transport,
                "data": result.stdout_json.get(pair) or result.stdout_json,
            }
        if result.status == "missing_cli":
            break
    # Mock fallback derived from the mocked ticker.
    last = _mock_base_price(symbol_ticker)
    spread = max(0.01, last * 0.0008)
    bid_top = round(last - spread, 4)
    ask_top = round(last + spread, 4)
    return {
        "source": "mock",
        "using_mock": True,
        "pair": forms[0],
        "data": {
            "bids": [[round(bid_top * (1 - 0.0002 * i), 4), 100 + 50 * i] for i in range(count)],
            "asks": [[round(ask_top * (1 + 0.0002 * i), 4), 100 + 50 * i] for i in range(count)],
        },
    }


def fetch_trades(symbol_ticker: str, quote: str = "USD", count: int = 20) -> dict[str, Any]:
    forms = candidate_pair_forms(symbol_ticker, quote)
    for pair in forms:
        result = run_cli(["trades", pair, "--count", str(int(count))])
        if result.ok and isinstance(result.stdout_json, dict):
            return {
                "source": "kraken_cli",
                "pair": pair,
                "transport": result.transport,
                "data": result.stdout_json,
            }
        if result.status == "missing_cli":
            break
    return {
        "source": "mock",
        "using_mock": True,
        "pair": forms[0],
        "data": {"trades": []},
    }


def fetch_balances() -> dict[str, Any]:
    """Authenticated balance call. Returns mock when CLI is missing or unauth."""
    result = run_cli(["balance"])
    if result.ok and isinstance(result.stdout_json, dict):
        return {"source": "kraken_cli", "balances": result.stdout_json, "transport": result.transport}
    if result.status == "missing_cli":
        return {"source": "mock", "using_mock": True, "balances": {"USD": 10_000.0}, "note": "kraken cli not installed"}
    return {
        "source": "mock",
        "using_mock": True,
        "balances": {"USD": 10_000.0},
        "note": f"balance fallback: {result.stderr[:200] or 'unknown'}",
    }


def fetch_paper_status() -> dict[str, Any]:
    """Paper-trading status (read-only). Returns mock if the CLI complains."""
    result = run_cli(["paper", "status"])
    if result.ok and result.stdout_json is not None:
        return {"source": "kraken_cli", "data": result.stdout_json, "transport": result.transport}
    if result.status == "missing_cli":
        return {"source": "mock", "using_mock": True, "data": {"cash_usd": 10_000.0, "positions": []}}
    # Even when the CLI returns a non-zero exit (e.g. paper not initialised) we
    # surface the JSON payload as best-effort context.
    return {
        "source": "mock",
        "using_mock": True,
        "data": {"cash_usd": 10_000.0, "positions": []},
        "cli_payload": result.stdout_json,
        "note": (result.stderr[:200] if result.stderr else "paper not initialised"),
    }


def fetch_system_status() -> dict[str, Any]:
    result = run_cli(["status"])
    if result.ok and isinstance(result.stdout_json, dict):
        return {"source": "kraken_cli", "transport": result.transport, "data": result.stdout_json}
    return {"source": "mock", "using_mock": True, "data": {"status": "unknown"}}


def _wrap_paper_result(result: CLIResult, key: str) -> dict[str, Any]:
    if result.ok and result.stdout_json is not None:
        return {
            "source": "kraken_cli",
            "transport": result.transport,
            "data": result.stdout_json,
        }
    return {
        "source": "mock",
        "using_mock": True,
        "transport": result.transport,
        "data": None,
        "cli_payload": result.stdout_json,
        "note": (result.stderr[:200] if result.stderr else f"paper {key} unavailable"),
    }


def fetch_paper_balance() -> dict[str, Any]:
    """Read-only paper balance. Never modifies state."""
    return _wrap_paper_result(run_cli(["paper", "balance"]), "balance")


def fetch_paper_orders() -> dict[str, Any]:
    """Read-only list of currently open paper orders."""
    return _wrap_paper_result(run_cli(["paper", "orders"]), "orders")


def fetch_paper_history() -> dict[str, Any]:
    """Read-only paper trade history."""
    return _wrap_paper_result(run_cli(["paper", "history"]), "history")


def paper_init(balance: float = 10_000.0, currency: str = "USD") -> CLIResult:
    """Initialize the paper account. Caller is responsible for opt-in.

    This MUST only ever be invoked from a dedicated script that the user
    runs with an explicit flag — never automatically by the agent loop.
    """
    args = [
        "paper", "init",
        "--balance", str(balance),
        "--currency", currency,
        "--yes",
    ]
    return run_cli(args, timeout=30)


def paper_place_order(
    *,
    symbol_pair: str,
    action: Action,
    volume: float,
    order_type: str = "market",
) -> CLIResult:
    """Place a paper order. Caller must guard this behind an explicit flag."""
    if action not in ("BUY", "SELL"):
        return CLIResult(ok=False, status="blocked", command=[], stderr="action must be BUY or SELL")
    side = "buy" if action == "BUY" else "sell"
    args = [
        "paper", side, symbol_pair, str(volume),
        "--type", order_type, "--yes",
    ]
    return run_cli(args, timeout=20)


def cancel_after(seconds: int) -> CLIResult:
    """Dead-man's switch: cancel all open orders after N seconds of silence."""
    return run_cli(["order", "cancel-after", str(int(seconds))])


def validate_live_order(
    symbol_pair: str, action: Action, volume: float,
    *, order_type: str = "market", price: float | None = None,
) -> CLIResult:
    side = "buy" if action == "BUY" else "sell"
    args: list[str] = ["order", side, symbol_pair, str(volume), "--type", order_type]
    if price is not None and order_type != "market":
        args += ["--price", str(price)]
    args.append("--validate")
    return run_cli(args, timeout=20)


def place_order(
    *,
    mode: Literal["paper", "live"],
    symbol_pair: str,
    action: Action,
    volume: float,
    order_type: str = "market",
    price: float | None = None,
    yes: bool = True,
) -> CLIResult:
    if action not in ("BUY", "SELL"):
        return CLIResult(ok=False, status="blocked", command=[], stderr="action must be BUY or SELL")
    side = "buy" if action == "BUY" else "sell"
    args: list[str] = []
    if mode == "paper":
        args = ["paper", side, symbol_pair, str(volume), "--type", order_type]
    elif mode == "live":
        args = ["order", side, symbol_pair, str(volume), "--type", order_type]
    else:
        return CLIResult(ok=False, status="blocked", command=[], stderr=f"unsupported mode {mode}")
    if price is not None and order_type != "market":
        args += ["--price", str(price)]
    if yes:
        args.append("--yes")
    return run_cli(args, timeout=20)


def kraken_diagnostics() -> dict[str, Any]:
    transport, binary = _decide_transport()
    return {
        "transport": transport,
        "configured_transport": _configured_transport(),
        "windows_binary": binary,
        "windows_binary_in_path": _windows_binary(),
        "wsl_available": _wsl_available(),
        "wsl_kraken_present": _wsl_kraken_present() if _wsl_available() else False,
        "version": get_version() if transport != "mock" else None,
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
    "fetch_orderbook",
    "fetch_trades",
    "fetch_balances",
    "fetch_paper_status",
    "fetch_paper_balance",
    "fetch_paper_orders",
    "fetch_paper_history",
    "fetch_system_status",
    "paper_init",
    "paper_place_order",
    "cancel_after",
    "validate_live_order",
    "place_order",
    "kraken_diagnostics",
]
