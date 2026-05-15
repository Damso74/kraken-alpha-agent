"""Validate-only check for xStocks Perpetual Futures via Kraken Futures CLI.

Kraken Futures order subcommand does **not** expose a ``--validate`` flag
(confirmed against ``kraken 0.3.2`` on 2026-05-15). To keep the safety
contract of the spot validate script while using the new engine, this
script routes through ``kraken futures paper buy/sell <PF_xxx>``, which:

* Uses the same authentication path as live orders.
* Runs against real market data (mark price, funding rate, tick).
* Cannot touch mainnet collateral — the simulated fill happens on the
  Kraken Futures paper engine.

Outputs (machine-readable + redacted):

* ``data/validate_live_xstocks_perps_<timestamp>.json``
* ``data/validate_live_xstocks_perps_latest.json``

Safety contract:

* Refuses to run when ``KRAKEN_FUTURES_API_KEY`` / ``KRAKEN_FUTURES_API_SECRET``
  are empty (the paper engine is auth-gated for futures).
* Forces ``--leverage 1`` on every paper call.
* Never opens a short: the script only sends BUY paper orders. SELL paths
  are exercised by the live preflight via the runtime portfolio state.
* API keys are read from env only and never printed.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from src.futures_kraken_cli import (  # noqa: E402  (sys.path mutation)
    HARDCODED_MAX_LEVERAGE,
    SPOT_TO_FUTURES,
    to_futures_symbol,
)


DEFAULT_SYMBOLS = ("AAPLx/USD", "NVDAx/USD", "TSLAx/USD")
DEFAULT_SIZE_CONTRACTS = 0.001
SOURCE_LABEL = "validate_only_futures_perps"
WARNING = (
    "validate-only via kraken futures paper engine — no mainnet order "
    "submitted; uses real market data on a simulated collateral pool"
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _mask(value: str | None, env: dict[str, str]) -> str:
    if not value:
        return ""
    masked = value
    for key in (
        "KRAKEN_FUTURES_API_KEY", "KRAKEN_FUTURES_API_SECRET",
        "KRAKEN_API_KEY", "KRAKEN_API_SECRET", "FEATHERLESS_API_KEY",
    ):
        secret = env.get(key) or ""
        if secret and len(secret) >= 6 and secret in masked:
            masked = masked.replace(secret, "***")
    return masked


def build_paper_command(
    *,
    futures_symbol: str,
    size: float,
    side: str = "buy",
    leverage: float = 1.0,
    client_order_id: Optional[str] = None,
) -> list[str]:
    """Return the argv list for one paper futures validate call.

    Every command this builder produces uses ``--type market`` and
    ``--leverage 1``. ``--leverage`` above ``HARDCODED_MAX_LEVERAGE``
    raises. ``futures_symbol`` MUST start with ``PF_`` (xStocks Perps
    convention) — anything else raises ``ValueError``.
    """

    if side.lower() not in ("buy", "sell"):
        raise ValueError(f"side must be buy/sell, got {side!r}")
    if not futures_symbol.startswith("PF_"):
        raise ValueError(
            f"futures symbol must start with PF_, got {futures_symbol!r}"
        )
    if float(size) <= 0:
        raise ValueError(f"size must be > 0, got {size!r}")
    if leverage > HARDCODED_MAX_LEVERAGE:
        raise ValueError(
            f"leverage {leverage} exceeds hardcoded cap "
            f"{HARDCODED_MAX_LEVERAGE} (intransigeant: spot-equivalent 1x only)"
        )

    args = [
        "futures", "paper", side.lower(), futures_symbol, str(size),
        "--type", "market",
        "--leverage", str(min(float(leverage), HARDCODED_MAX_LEVERAGE)),
    ]
    if client_order_id:
        args += ["--client-order-id", client_order_id]
    args += ["--yes", "-o", "json"]
    return args


def _wrap_with_transport(args: list[str]) -> tuple[list[str], str]:
    if os.name == "nt":
        return (
            [
                "wsl", "--", "bash", "-lc",
                "kraken " + " ".join(shlex.quote(a) for a in args),
            ],
            "wsl",
        )
    return (["kraken", *args], "native")


def _parse_stdout(text: str) -> Any:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text[:400]


def _run_one(
    spot_symbol: str,
    size: float,
    *,
    timeout: float,
    env: dict[str, str],
    client_order_id: str,
) -> dict[str, Any]:
    futures_symbol = to_futures_symbol(spot_symbol)
    if futures_symbol is None:
        return {
            "symbol": spot_symbol,
            "futures_symbol": None,
            "ok": False,
            "error": f"no futures listing for {spot_symbol}",
            "command": [],
            "stdout_json": None,
            "stderr": "",
            "exit_code": None,
            "transport": None,
        }
    args = build_paper_command(
        futures_symbol=futures_symbol, size=size,
        side="buy", leverage=1.0,
        client_order_id=client_order_id,
    )
    cmd, transport = _wrap_with_transport(args)
    masked_cmd = [_mask(part, env) for part in cmd]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, env=env, encoding="utf-8",
        )
    except FileNotFoundError as exc:
        return {
            "symbol": spot_symbol, "futures_symbol": futures_symbol,
            "ok": False, "command": masked_cmd, "stdout_json": None,
            "stderr": _mask(str(exc), env), "exit_code": None,
            "transport": transport, "error": "kraken CLI binary not found",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "symbol": spot_symbol, "futures_symbol": futures_symbol,
            "ok": False, "command": masked_cmd, "stdout_json": None,
            "stderr": _mask(f"timeout after {timeout}s: {exc}", env),
            "exit_code": None, "transport": transport, "error": "timeout",
        }
    return {
        "symbol": spot_symbol, "futures_symbol": futures_symbol,
        "ok": proc.returncode == 0, "command": masked_cmd,
        "stdout_json": _parse_stdout(proc.stdout or ""),
        "stderr": _mask((proc.stderr or "").strip(), env),
        "exit_code": proc.returncode, "transport": transport,
    }


def _build_env(api_key: str | None, api_secret: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if api_key:
        env["KRAKEN_FUTURES_API_KEY"] = api_key
        env.setdefault("KRAKEN_API_KEY", api_key)
    if api_secret:
        env["KRAKEN_FUTURES_API_SECRET"] = api_secret
        env.setdefault("KRAKEN_API_SECRET", api_secret)
    return env


def _check_keys() -> tuple[bool, str]:
    key = (
        os.environ.get("KRAKEN_FUTURES_API_KEY")
        or os.environ.get("KRAKEN_API_KEY")
        or ""
    )
    secret = (
        os.environ.get("KRAKEN_FUTURES_API_SECRET")
        or os.environ.get("KRAKEN_API_SECRET")
        or ""
    )
    if not key or not secret:
        return False, (
            "KRAKEN_FUTURES_API_KEY / KRAKEN_FUTURES_API_SECRET (or the spot "
            "fallbacks) are empty. The futures paper engine is auth-gated — "
            "populate your .env with the keys created on "
            "https://futures.kraken.com. No values displayed."
        )
    return True, ""


def _write_outputs(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamped = output_dir / f"validate_live_xstocks_perps_{_stamp()}.json"
    latest = output_dir / "validate_live_xstocks_perps_latest.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    stamped.write_text(body, encoding="utf-8")
    latest.write_text(body, encoding="utf-8")
    return stamped, latest


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Validate-only Kraken Futures Perpetual xStocks check. Uses the "
            "futures paper engine as the validate fallback because "
            "'kraken futures order buy' has no --validate flag."
        )
    )
    p.add_argument(
        "--symbols", nargs="+",
        default=list(DEFAULT_SYMBOLS),
        help=f"slash-form xStocks pairs (default: {' '.join(DEFAULT_SYMBOLS)})",
    )
    p.add_argument(
        "--size", type=float, default=DEFAULT_SIZE_CONTRACTS,
        help=f"tiny contract size (default: {DEFAULT_SIZE_CONTRACTS})",
    )
    p.add_argument("--timeout", type=float, default=25.0, help="per-call timeout (seconds)")
    p.add_argument(
        "--output-dir", type=Path, default=ROOT / "data",
        help="directory where validate_live_xstocks_perps_<ts>.json is written",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    keys_ok, key_error = _check_keys()
    timestamp = _utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")
    known_mapping = dict(SPOT_TO_FUTURES)

    if not keys_ok:
        payload = {
            "timestamp": timestamp, "source": SOURCE_LABEL,
            "warning": WARNING, "ok": False, "error": key_error,
            "symbols": list(args.symbols), "futures_mapping": known_mapping,
            "results": [], "transport": None,
        }
        stamped, latest = _write_outputs(payload, args.output_dir)
        print(key_error)
        print(f"wrote {stamped}")
        print(f"wrote {latest}")
        return 2

    env = _build_env(
        os.environ.get("KRAKEN_FUTURES_API_KEY")
        or os.environ.get("KRAKEN_API_KEY"),
        os.environ.get("KRAKEN_FUTURES_API_SECRET")
        or os.environ.get("KRAKEN_API_SECRET"),
    )

    results: list[dict[str, Any]] = []
    transport_seen: Optional[str] = None
    commands: list[list[str]] = []
    for sym in args.symbols:
        res = _run_one(
            sym, args.size,
            timeout=args.timeout, env=env,
            client_order_id=f"validate-{_stamp()}-{sym.replace('/', '')}",
        )
        results.append(res)
        if transport_seen is None and res.get("transport"):
            transport_seen = str(res["transport"])
        commands.append(res.get("command") or [])

    any_ok = any(r.get("ok") for r in results)
    payload = {
        "timestamp": timestamp, "source": SOURCE_LABEL,
        "warning": WARNING, "ok": any_ok, "transport": transport_seen,
        "symbols": list(args.symbols),
        "futures_mapping": known_mapping,
        "commands": commands, "results": results,
    }
    stamped, latest = _write_outputs(payload, args.output_dir)
    for r in results:
        status = "OK" if r.get("ok") else "FAIL"
        sym_label = f"{r['symbol']} -> {r.get('futures_symbol') or 'n/a'}"
        print(f"[{status}] {sym_label} (exit={r.get('exit_code')})")
        if r.get("stderr"):
            print(f"       stderr: {r['stderr'][:160]}")
    print(f"wrote {stamped}")
    print(f"wrote {latest}")
    return 0 if any_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
