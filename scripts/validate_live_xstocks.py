"""Validate-only xStocks order check against the live Kraken endpoint.

Goal: confirm that ``kraken order buy <PAIR> <VOL> --type market
--asset-class tokenized_asset --validate`` is accepted by Kraken without
actually submitting an order. Every command this script builds carries
the ``--validate`` flag; the builder raises :class:`MissingValidateError`
if the flag is missing, so it is structurally impossible to send a real
order from here.

Outputs (machine-readable + redacted):
- ``data/validate_live_xstocks_<timestamp>.json``
- ``data/validate_live_xstocks_latest.json``

Safety contract:
- NEVER omits ``--validate``.
- NEVER calls ``kraken paper buy/sell`` and never imports
  ``src.execution``.
- API keys are read from env only and never printed.
- Refuses to run when ``KRAKEN_API_KEY``/``KRAKEN_API_SECRET`` are empty
  (the validate endpoint requires auth) — the script prints a clean
  error instead of crashing.
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


DEFAULT_SYMBOLS = ("AAPLx/USD", "NVDAx/USD", "TSLAx/USD")
DEFAULT_VOLUME = 0.001
SOURCE_LABEL = "validate_only"
WARNING = "validate-only, no order submitted"


class MissingValidateError(RuntimeError):
    """Raised when a command is built without the mandatory ``--validate`` flag."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp() -> str:
    return _utc_now().strftime("%Y%m%dT%H%M%SZ")


def _mask(value: str | None, env: dict[str, str]) -> str:
    if not value:
        return ""
    masked = value
    for key in ("KRAKEN_API_KEY", "KRAKEN_API_SECRET", "FEATHERLESS_API_KEY"):
        secret = env.get(key) or ""
        if secret and len(secret) >= 6 and secret in masked:
            masked = masked.replace(secret, "***")
    return masked


def build_validate_command(
    *,
    symbol_pair: str,
    volume: float,
    side: str = "buy",
    order_type: str = "market",
) -> list[str]:
    """Return the argv list for one validate-only Kraken CLI invocation.

    Raises :class:`MissingValidateError` if the resulting argv lacks
    ``--validate``. Callers MUST use this builder; they MUST NOT splice
    the flag out afterwards.
    """
    if side.lower() not in ("buy", "sell"):
        raise ValueError(f"side must be buy/sell, got {side!r}")
    if not symbol_pair or "/" not in symbol_pair:
        raise ValueError(f"symbol must be slash form (e.g. AAPLx/USD), got {symbol_pair!r}")
    if float(volume) <= 0:
        raise ValueError(f"volume must be > 0, got {volume!r}")

    args = [
        "order",
        side.lower(),
        symbol_pair,
        str(volume),
        "--type",
        order_type,
        "--asset-class",
        "tokenized_asset",
        "--validate",
        "-o",
        "json",
    ]
    if "--validate" not in args:
        # Pure defence-in-depth — the literal above already includes the flag.
        raise MissingValidateError(
            "refusing to build a kraken order command without --validate"
        )
    return args


def _wrap_with_transport(args: list[str]) -> tuple[list[str], str]:
    """Wrap ``args`` in either a direct call or ``wsl -- bash -lc``.

    Mirrors the logic in ``src.kraken_cli`` but kept inline so this script
    never falls back to mock mode by accident — we always shell out to the
    real CLI for the validate run. Returns ``(cmd, transport_label)``.
    """
    if os.name == "nt":
        return (["wsl", "--", "bash", "-lc", "kraken " + " ".join(shlex.quote(a) for a in args)], "wsl")
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
    symbol_pair: str,
    volume: float,
    *,
    timeout: float,
    env: dict[str, str],
) -> dict[str, Any]:
    args = build_validate_command(symbol_pair=symbol_pair, volume=volume)
    if "--validate" not in args:  # belt + suspenders
        raise MissingValidateError("--validate flag missing right before subprocess call")
    cmd, transport = _wrap_with_transport(args)
    masked_cmd = [_mask(part, env) for part in cmd]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        return {
            "symbol": symbol_pair,
            "ok": False,
            "command": masked_cmd,
            "stdout_json": None,
            "stderr": _mask(str(exc), env),
            "exit_code": None,
            "transport": transport,
            "error": "kraken CLI binary not found",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "symbol": symbol_pair,
            "ok": False,
            "command": masked_cmd,
            "stdout_json": None,
            "stderr": _mask(f"timeout after {timeout}s: {exc}", env),
            "exit_code": None,
            "transport": transport,
            "error": "timeout",
        }

    stdout_json = _parse_stdout(proc.stdout or "")
    stderr = _mask((proc.stderr or "").strip(), env)
    return {
        "symbol": symbol_pair,
        "ok": proc.returncode == 0,
        "command": masked_cmd,
        "stdout_json": stdout_json,
        "stderr": stderr,
        "exit_code": proc.returncode,
        "transport": transport,
    }


def _build_env(api_key: str | None, api_secret: str | None) -> dict[str, str]:
    env = os.environ.copy()
    if api_key:
        env["KRAKEN_API_KEY"] = api_key
    if api_secret:
        env["KRAKEN_API_SECRET"] = api_secret
    return env


def _check_keys() -> tuple[bool, str]:
    key = os.environ.get("KRAKEN_API_KEY") or ""
    secret = os.environ.get("KRAKEN_API_SECRET") or ""
    if not key or not secret:
        return False, (
            "KRAKEN_API_KEY / KRAKEN_API_SECRET are empty. The validate "
            "endpoint requires auth — populate your .env (read-only key is "
            "fine for validate). No values displayed."
        )
    return True, ""


def _write_outputs(payload: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamped = output_dir / f"validate_live_xstocks_{_stamp()}.json"
    latest = output_dir / "validate_live_xstocks_latest.json"
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    stamped.write_text(body, encoding="utf-8")
    latest.write_text(body, encoding="utf-8")
    return stamped, latest


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Validate-only xStocks check. Calls 'kraken order buy <PAIR> "
            "<VOL> --type market --asset-class tokenized_asset --validate' "
            "for each symbol. NEVER places an order."
        )
    )
    p.add_argument(
        "--symbols",
        nargs="+",
        default=list(DEFAULT_SYMBOLS),
        help=f"slash-form xStocks pairs (default: {' '.join(DEFAULT_SYMBOLS)})",
    )
    p.add_argument(
        "--volume",
        type=float,
        default=DEFAULT_VOLUME,
        help=f"tiny test volume (default: {DEFAULT_VOLUME})",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=20.0,
        help="per-call timeout (seconds)",
    )
    p.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "data",
        help="directory where validate_live_xstocks_<ts>.json is written",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    keys_ok, key_error = _check_keys()
    timestamp = _utc_now().isoformat(timespec="seconds").replace("+00:00", "Z")

    if not keys_ok:
        payload = {
            "timestamp": timestamp,
            "source": SOURCE_LABEL,
            "warning": WARNING,
            "ok": False,
            "error": key_error,
            "symbols": list(args.symbols),
            "results": [],
            "transport": None,
        }
        stamped, latest = _write_outputs(payload, args.output_dir)
        print(key_error)
        print(f"wrote {stamped}")
        print(f"wrote {latest}")
        return 2

    env = _build_env(
        os.environ.get("KRAKEN_API_KEY"),
        os.environ.get("KRAKEN_API_SECRET"),
    )

    results: list[dict[str, Any]] = []
    transport_seen: Optional[str] = None
    commands: list[list[str]] = []
    for sym in args.symbols:
        res = _run_one(
            sym,
            args.volume,
            timeout=args.timeout,
            env=env,
        )
        results.append(res)
        if transport_seen is None and res.get("transport"):
            transport_seen = str(res["transport"])
        commands.append(res.get("command") or [])

    any_ok = any(r.get("ok") for r in results)
    payload = {
        "timestamp": timestamp,
        "source": SOURCE_LABEL,
        "warning": WARNING,
        "ok": any_ok,
        "transport": transport_seen,
        "symbols": list(args.symbols),
        "commands": commands,
        "results": results,
    }
    stamped, latest = _write_outputs(payload, args.output_dir)
    for r in results:
        status = "OK" if r.get("ok") else "FAIL"
        print(f"[{status}] {r['symbol']} (exit={r.get('exit_code')})")
        if r.get("stderr"):
            print(f"       stderr: {r['stderr'][:160]}")
    print(f"wrote {stamped}")
    print(f"wrote {latest}")
    return 0 if any_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
