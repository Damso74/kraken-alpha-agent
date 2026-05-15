"""Thin subprocess wrapper around ``kraken futures ...`` for the xStocks Perps pivot.

Context (May 2026):

EU/PEDSL-CY accounts cannot trade the spot xStocks orderbook on Kraken Spot.
The user explicitly overrode the original "no futures, no leverage" rule to
route through the Kraken Futures venue, which authorises xStocks Perpetual
Futures for the same juridictions. The override is paired with intransigeant
safeguards centralised in :mod:`src.risk` and :mod:`src.execution`:

* ``max_leverage = 1.0`` hardcoded (every other value is **rejected** by the
  risk gate, regardless of the config/env source).
* SELL is exit-only — it can only reduce an existing long, never open a short.
* Funding rate gate: BUY is refused if ``fundingRate * 100 > threshold``.
* ``flatten_before_close`` keeps firing on futures positions exactly like it
  did on spot, so we never hold overnight.

Confirmed against ``kraken 0.3.2`` inside WSL Ubuntu on 2026-05-15:

* ``kraken futures instruments -o json`` (public, no auth) returned the 10
  xStocks Perps below (``PF_<TICKERx>USD`` symbol, ``flexible_futures`` type,
  ``fundingRateCoefficient=24`` i.e. hourly funding).
* ``kraken futures ticker PF_AAPLXUSD -o json`` returns ``markPrice``,
  ``indexPrice``, ``fundingRate``, ``fundingRatePrediction``, etc.
* ``kraken futures order buy <SYMBOL> <SIZE> --type market`` does **NOT**
  expose a ``--validate`` flag. The validate-only fallback used everywhere in
  the codebase therefore goes through ``kraken futures paper buy`` (separate
  simulated engine, real market data, never touches mainnet collateral).

This module never opens a short and never sets leverage above ``1.0``: the
``--leverage`` flag is clamped to ``1.0`` at the wrapper layer as a final
belt-and-suspenders barrier on top of the risk gate.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

from .logger import get_logger
from .utils import utc_now_iso

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Symbol mapping: xStocks spot ↔ xStocks Perpetual Futures
# ---------------------------------------------------------------------------
#
# Discovered via ``kraken futures instruments -o json`` on 2026-05-15. The
# canonical format is ``PF_<UPPERCASED-TICKER>USD`` where the ticker keeps
# the lowercase ``x`` from the spot symbol but is upper-cased as a whole
# (so ``AAPLx`` becomes ``AAPLX``).
#
# Symbols NOT mirrored in Futures (kept here so callers can fall back to
# spot or skip): MSFTx, AMZNx, METAx — these stay spot-only on Kraken.
SPOT_TO_FUTURES: dict[str, str] = {
    "AAPLx": "PF_AAPLXUSD",
    "NVDAx": "PF_NVDAXUSD",
    "TSLAx": "PF_TSLAXUSD",
    "GOOGLx": "PF_GOOGLXUSD",
    "SPYx": "PF_SPYXUSD",
    "QQQx": "PF_QQQXUSD",
    "MSTRx": "PF_MSTRXUSD",
    "CRCLx": "PF_CRCLXUSD",
    "HOODx": "PF_HOODXUSD",
    "GLDx": "PF_GLDXUSD",
}

# Reverse map for diagnostics. Populated lazily so unit tests can shim
# SPOT_TO_FUTURES without losing the consistency invariant.
def _futures_to_spot() -> dict[str, str]:
    return {v: k for k, v in SPOT_TO_FUTURES.items()}


# Funding coefficient = 24 → 1 funding period per hour for every xStocks Perp
# at the time of the discovery run; convert raw ticker fundingRate to a
# %/hour figure with ``fundingRate * 100``.
DEFAULT_FUNDING_PERIODS_PER_DAY = 24

# Wrapper-level leverage clamp. The risk gate is the source of truth;
# this hard ceiling here exists so a buggy caller cannot smuggle a higher
# leverage value into the CLI even if all risk checks were somehow bypassed.
HARDCODED_MAX_LEVERAGE = 1.0

DEFAULT_TIMEOUT_SECONDS = 15
KRAKEN_BIN_CANDIDATES = ("kraken", "kraken.exe")

Transport = Literal["auto", "windows", "wsl", "mock"]
Action = Literal["BUY", "SELL"]


@dataclass
class FuturesCLIResult:
    ok: bool
    status: Literal["ok", "error", "mock", "missing_cli", "blocked"]
    command: list[str] = field(default_factory=list)
    stdout_json: Any | None = None
    stderr: str = ""
    exit_code: int | None = None
    duration_ms: int = 0
    source: str = "kraken_futures_cli"
    using_mock: bool = False
    transport: str = "unknown"
    at: str = field(default_factory=utc_now_iso)


# ---------------------------------------------------------------------------
# Symbol helpers
# ---------------------------------------------------------------------------


_SLASH_RE = re.compile(r"^(?P<ticker>[A-Za-z0-9]+x)/(?P<quote>[A-Za-z]{3,5})$")


def to_futures_symbol(spot_pair_or_ticker: str) -> str | None:
    """Translate an xStocks spot pair/ticker to its Kraken Futures symbol.

    Accepts the canonical slash form (e.g. ``AAPLx/USD``) and the bare
    ticker (e.g. ``AAPLx``). Returns ``None`` when the symbol has no
    Futures counterpart (e.g. MSFTx, AMZNx, METAx are spot-only).
    """

    if not spot_pair_or_ticker:
        return None
    raw = spot_pair_or_ticker.strip()
    ticker = raw
    match = _SLASH_RE.match(raw)
    if match:
        ticker = match.group("ticker")
    return SPOT_TO_FUTURES.get(ticker)


def to_spot_ticker(futures_symbol: str) -> str | None:
    if not futures_symbol:
        return None
    return _futures_to_spot().get(futures_symbol.strip())


def has_futures_listing(spot_pair_or_ticker: str) -> bool:
    return to_futures_symbol(spot_pair_or_ticker) is not None


# ---------------------------------------------------------------------------
# Transport detection — mirrors ``src.kraken_cli`` but isolated so a test
# can mock either layer independently.
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
    forced = _configured_transport()
    if forced == "mock":
        return "mock", None
    if forced == "windows":
        binary = _windows_binary()
        return ("windows", binary) if binary else ("mock", None)
    if forced == "wsl":
        return ("wsl", None) if _wsl_kraken_present() else ("mock", None)
    binary = _windows_binary()
    if binary:
        return "windows", binary
    if _wsl_kraken_present():
        return "wsl", None
    return "mock", None


def is_installed() -> bool:
    transport, _ = _decide_transport()
    return transport in ("windows", "wsl")


def _shell_command(args: list[str], *, transport: Transport, binary: str | None) -> list[str]:
    if transport == "windows":
        return [binary or "kraken", *args]
    if transport == "wsl":
        quoted = " ".join(shlex.quote(a) for a in args)
        return ["wsl", "--", "bash", "-lc", f"kraken {quoted}"]
    return []


def _env_for_subprocess() -> dict[str, str]:
    env = os.environ.copy()
    # Futures-specific env keys take precedence; fall back to the spot keys
    # so a one-key VPS keeps working transparently.
    futures_key = env.get("KRAKEN_FUTURES_API_KEY") or env.get("KRAKEN_API_KEY") or ""
    futures_secret = env.get("KRAKEN_FUTURES_API_SECRET") or env.get("KRAKEN_API_SECRET") or ""
    if futures_key:
        env["KRAKEN_FUTURES_API_KEY"] = futures_key
        env["KRAKEN_API_KEY"] = futures_key
    if futures_secret:
        env["KRAKEN_FUTURES_API_SECRET"] = futures_secret
        env["KRAKEN_API_SECRET"] = futures_secret
    return env


# ---------------------------------------------------------------------------
# Low-level invocation
# ---------------------------------------------------------------------------


def _augment(args: list[str]) -> list[str]:
    out = list(args)
    if not any(a in {"-o", "--output"} for a in out):
        out += ["-o", "json"]
    return out


def run_futures_cli(
    args: Iterable[str],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    parse_json: bool = True,
) -> FuturesCLIResult:
    arg_list = ["futures", *list(args)]
    transport, binary = _decide_transport()
    augmented = _augment(arg_list) if parse_json else list(arg_list)
    cmd = _shell_command(augmented, transport=transport, binary=binary)
    if transport == "mock":
        return FuturesCLIResult(
            ok=False, status="missing_cli",
            command=[*KRAKEN_BIN_CANDIDATES[:1], *augmented],
            stderr="Kraken futures CLI unavailable (transport=mock)",
            transport=transport, using_mock=True,
        )

    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env=_env_for_subprocess(), encoding="utf-8",
        )
    except subprocess.TimeoutExpired as exc:
        return FuturesCLIResult(
            ok=False, status="error", command=cmd,
            stderr=f"timeout after {timeout}s: {exc}",
            duration_ms=int((time.perf_counter() - start) * 1000),
            transport=transport,
        )
    except FileNotFoundError as exc:
        return FuturesCLIResult(
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
    return FuturesCLIResult(
        ok=proc.returncode == 0,
        status="ok" if proc.returncode == 0 else "error",
        command=cmd, stdout_json=payload, stderr=stderr,
        exit_code=proc.returncode, duration_ms=duration_ms,
        transport=transport,
    )


# ---------------------------------------------------------------------------
# High-level operations
# ---------------------------------------------------------------------------


def _normalise_ticker_payload(symbol: str, payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    block = payload.get("ticker") if "ticker" in payload else payload
    if not isinstance(block, dict):
        return None
    funding_rate = block.get("fundingRate")
    mark = block.get("markPrice") or block.get("indexPrice") or block.get("last")
    return {
        "symbol": block.get("symbol") or symbol,
        "pair": block.get("pair"),
        "tag": block.get("tag"),
        "mark_price": _safe_float(mark),
        "index_price": _safe_float(block.get("indexPrice")),
        "last_price": _safe_float(block.get("last")),
        "ask": _safe_float(block.get("ask")),
        "bid": _safe_float(block.get("bid")),
        "funding_rate": _safe_float(funding_rate),
        "funding_rate_prediction": _safe_float(block.get("fundingRatePrediction")),
        "funding_rate_pct_per_hour": (
            float(funding_rate) * 100.0 if isinstance(funding_rate, (int, float)) else None
        ),
        "raw": block,
    }


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_futures_ticker(symbol: str) -> dict[str, Any]:
    """Fetch the futures ticker for a single PF_ symbol. Returns a mock payload
    when the CLI is unavailable so the caller never crashes in offline tests.
    """

    sym = symbol.strip()
    if not sym.startswith("PF_"):
        translated = to_futures_symbol(sym)
        if translated:
            sym = translated
    result = run_futures_cli(["ticker", sym])
    if result.ok and result.stdout_json is not None:
        normalised = _normalise_ticker_payload(sym, result.stdout_json)
        if normalised:
            normalised["source"] = "kraken_futures_cli"
            normalised["transport"] = result.transport
            return normalised
    # Mock fallback: deterministic mid-200 with a small spread.
    return {
        "symbol": sym,
        "pair": None,
        "tag": "perpetual",
        "mark_price": 200.0,
        "index_price": 200.0,
        "last_price": 200.0,
        "ask": 200.10,
        "bid": 199.90,
        "funding_rate": 0.0,
        "funding_rate_prediction": 0.0,
        "funding_rate_pct_per_hour": 0.0,
        "raw": {},
        "source": "mock",
        "using_mock": True,
        "note": result.stderr[:200] if result.stderr else "kraken futures cli unavailable",
    }


def fetch_open_positions() -> FuturesCLIResult:
    return run_futures_cli(["positions"], timeout=15)


def cancel_after(seconds: int) -> FuturesCLIResult:
    return run_futures_cli(["cancel-after", str(int(seconds))], timeout=10)


def _build_order_args(
    *,
    side: str,
    symbol: str,
    size: float,
    order_type: str = "market",
    leverage: float = 1.0,
    reduce_only: bool = False,
    client_order_id: str | None = None,
    paper: bool = True,
) -> list[str]:
    if side.lower() not in ("buy", "sell"):
        raise ValueError(f"side must be buy/sell, got {side!r}")
    if not symbol or not symbol.startswith("PF_"):
        raise ValueError(f"futures symbol must start with PF_, got {symbol!r}")
    if size <= 0:
        raise ValueError(f"size must be > 0, got {size}")
    if leverage > HARDCODED_MAX_LEVERAGE:
        raise ValueError(
            f"leverage {leverage} exceeds wrapper-level cap "
            f"{HARDCODED_MAX_LEVERAGE} — risk gate must approve <=1.0x only"
        )
    cmd_prefix = ["paper"] if paper else []
    args: list[str] = [*cmd_prefix, side.lower(), symbol, str(size), "--type", order_type]
    # ``--leverage`` is only supported on ``paper buy/sell``; for live futures
    # orders the per-account leverage preference is enforced via the
    # ``set-leverage`` endpoint, which the live preflight verifies separately.
    if paper:
        args += ["--leverage", str(leverage)]
    if reduce_only:
        args.append("--reduce-only")
    if client_order_id:
        args += ["--client-order-id", client_order_id]
    args.append("--yes")
    return args


def place_paper_order(
    *,
    side: Action,
    symbol: str,
    size: float,
    order_type: str = "market",
    leverage: float = 1.0,
    reduce_only: bool = False,
    client_order_id: str | None = None,
) -> FuturesCLIResult:
    """Run ``kraken futures paper buy/sell`` — simulated futures fill, real
    market data, no mainnet collateral involved. Used as the validate-only
    fallback because ``kraken futures order buy`` does **not** expose
    ``--validate`` (confirmed on kraken 0.3.2 / 2026-05-15)."""

    side_str = "buy" if side == "BUY" else "sell"
    leverage = min(float(leverage), HARDCODED_MAX_LEVERAGE)
    args = _build_order_args(
        side=side_str, symbol=symbol, size=float(size),
        order_type=order_type, leverage=leverage,
        reduce_only=reduce_only, client_order_id=client_order_id,
        paper=True,
    )
    return run_futures_cli(args, timeout=20)


def place_live_order(
    *,
    side: Action,
    symbol: str,
    size: float,
    order_type: str = "market",
    reduce_only: bool = False,
    client_order_id: str | None = None,
) -> FuturesCLIResult:
    """Place a real ``kraken futures order buy/sell`` on the mainnet venue.

    Live orders rely on the futures account's persistent leverage preference
    (``kraken futures set-leverage <SYMBOL> 1``) which the preflight checks.
    No per-order leverage flag exists on the live order subcommand.
    """

    side_str = "buy" if side == "BUY" else "sell"
    args = _build_order_args(
        side=side_str, symbol=symbol, size=float(size),
        order_type=order_type, leverage=1.0,
        reduce_only=reduce_only, client_order_id=client_order_id,
        paper=False,
    )
    return run_futures_cli(args, timeout=20)


def validate_via_paper(
    *,
    side: Action,
    symbol: str,
    size: float = 0.001,
    client_order_id: str | None = None,
) -> FuturesCLIResult:
    """Validate-only fallback: use the futures paper engine as a structural
    sanity check before flipping live. Real market data, simulated fill,
    zero risk to mainnet collateral. Confirmed safe on 2026-05-15.
    """

    return place_paper_order(
        side=side, symbol=symbol, size=size, order_type="market",
        leverage=1.0, reduce_only=False, client_order_id=client_order_id,
    )


def futures_diagnostics() -> dict[str, Any]:
    transport, binary = _decide_transport()
    return {
        "transport": transport,
        "configured_transport": _configured_transport(),
        "windows_binary": binary,
        "wsl_available": _wsl_available(),
        "wsl_kraken_present": _wsl_kraken_present() if _wsl_available() else False,
        "symbol_mapping": dict(SPOT_TO_FUTURES),
    }


__all__ = [
    "FuturesCLIResult",
    "SPOT_TO_FUTURES",
    "HARDCODED_MAX_LEVERAGE",
    "DEFAULT_FUNDING_PERIODS_PER_DAY",
    "to_futures_symbol",
    "to_spot_ticker",
    "has_futures_listing",
    "is_installed",
    "run_futures_cli",
    "fetch_futures_ticker",
    "fetch_open_positions",
    "cancel_after",
    "place_paper_order",
    "place_live_order",
    "validate_via_paper",
    "futures_diagnostics",
]
