"""Read-only probe of the Kraken CLI surface for xStocks.

For every xStock in the allowlist (plus a handful of explicitly requested
symbols), the script issues these read-only commands:

    kraken ticker     <PAIR> --asset-class tokenized_asset -o json
    kraken ohlc       <PAIR> --interval 60 --asset-class tokenized_asset -o json
    kraken orderbook  <PAIR> --count 10  --asset-class tokenized_asset -o json
    kraken trades     <PAIR> --count 20  --asset-class tokenized_asset -o json

Both the slash form (``AAPLx/USD``) and the compact form (``AAPLxUSD``) are
attempted; the first one accepted wins. **No order is ever placed.** No
authenticated call is performed.

Outputs:
- a human-readable summary on stdout
- a detailed JSON dump in ``data/probe_xstocks_<utc_iso>.json``

When the Kraken CLI is not available, the script reports the situation
cleanly and exits 0 (the dry-run still works against the mock fallback).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_settings  # noqa: E402
from src.kraken_cli import (  # noqa: E402
    fetch_system_status,
    is_installed,
    kraken_diagnostics,
    run_cli,
)
from src.logger import setup_logging  # noqa: E402
from src.universe import candidate_pair_forms, get_universe_tickers  # noqa: E402
from src.utils import utc_now_iso  # noqa: E402


_EXTRA_REQUESTED = ("AAPLx", "TSLAx", "NVDAx", "SPYx", "QQQx", "MSTRx")


def _trim(payload, limit: int = 600) -> str:
    if payload is None:
        return ""
    blob = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    return blob if len(blob) <= limit else blob[:limit] + "...[truncated]"


def _ordered_universe() -> list[str]:
    seen: set[str] = set()
    order: list[str] = []
    for sym in [*_EXTRA_REQUESTED, *get_universe_tickers()]:
        if sym not in seen:
            order.append(sym)
            seen.add(sym)
    return order


def _try_call(args: list[str]) -> dict:
    started = time.perf_counter()
    result = run_cli(args, timeout=15)
    elapsed = int((time.perf_counter() - started) * 1000)
    return {
        "args_user": args,
        "command_executed": result.command,
        "transport": result.transport,
        "ok": result.ok,
        "status": result.status,
        "exit_code": result.exit_code,
        "duration_ms": result.duration_ms or elapsed,
        "stderr": (result.stderr or "")[:400],
        "stdout_sample": _trim(result.stdout_json),
    }


def _probe_symbol(ticker: str, quote: str = "USD") -> dict:
    forms = candidate_pair_forms(ticker, quote)
    probes: dict[str, list[dict]] = {"ticker": [], "ohlc": [], "orderbook": [], "trades": []}
    chosen_form: str | None = None

    for pair in forms:
        call = _try_call(["ticker", pair])
        probes["ticker"].append({"pair": pair, **call})
        if call["ok"]:
            chosen_form = pair
            break

    target_pair = chosen_form or forms[0]
    for name, extra in [
        ("ohlc", ["--interval", "60"]),
        ("orderbook", ["--count", "10"]),
        ("trades", ["--count", "20"]),
    ]:
        call = _try_call([name, target_pair, *extra])
        probes[name].append({"pair": target_pair, **call})

    return {
        "ticker": ticker,
        "chosen_pair_form": chosen_form,
        "forms_attempted": forms,
        "probes": probes,
    }


def main() -> int:
    setup_logging()
    settings = get_settings()
    diag = kraken_diagnostics()

    print(f"Kraken Alpha Agent — Kraken CLI probe @ {utc_now_iso()}")
    print(f"transport: {diag['transport']} (configured={diag['configured_transport']})")
    print(f"version:   {diag.get('version') or '<unknown>'}")
    print(f"windows:   binary={diag['windows_binary'] or 'no'}  wsl_available={diag['wsl_available']}  wsl_kraken={diag['wsl_kraken_present']}")
    print()

    if not is_installed():
        print(
            "Kraken CLI is not available on this machine.\n"
            "  - On Linux/macOS / WSL Ubuntu, install via:\n"
            "      curl --proto '=https' --tlsv1.2 -LsSf \\\n"
            "        https://github.com/krakenfx/kraken-cli/releases/latest/download/kraken-cli-installer.sh | sh\n"
            "  - On Windows native: enable WSL and install inside the WSL distro.\n"
            "  - You can force the transport with KRAKEN_CLI_TRANSPORT=auto|windows|wsl|mock.\n"
            "Continuing with deterministic mock data (see CLI_VALIDATION.md)."
        )
        out_dir = settings.absolute_path("data")
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"probe_xstocks_{utc_now_iso().replace(':', '-')}.json"
        path.write_text(json.dumps({"diagnostics": diag, "results": []}, indent=2), encoding="utf-8")
        print(f"\nReport written to {path}")
        return 0

    system_status = fetch_system_status()
    print(f"kraken status: {system_status.get('data')}")
    print()

    print(f"Probing {len(_ordered_universe())} xStocks symbols (read-only)...\n")
    print(
        f"{'symbol':<10}{'form':<14}{'ticker':<10}{'ohlc':<10}{'orderbook':<12}{'trades':<10}"
    )
    print("-" * 66)

    results: list[dict] = []
    ok_count = 0
    err_count = 0
    mock_count = 0
    for ticker in _ordered_universe():
        report = _probe_symbol(ticker)
        results.append(report)

        def _summary(probe_list):
            if not probe_list:
                return "-"
            outcome = probe_list[-1]
            if outcome["ok"]:
                return f"ok {outcome['duration_ms']}ms"
            if outcome["status"] == "missing_cli":
                return "missing"
            return f"fail({outcome['exit_code']})"

        for category in ("ticker", "ohlc", "orderbook", "trades"):
            for probe in report["probes"][category]:
                if probe["ok"]:
                    ok_count += 1
                elif probe["status"] == "missing_cli":
                    mock_count += 1
                else:
                    err_count += 1

        print(
            f"{ticker:<10}{report['chosen_pair_form'] or '-':<14}"
            f"{_summary(report['probes']['ticker']):<10}"
            f"{_summary(report['probes']['ohlc']):<10}"
            f"{_summary(report['probes']['orderbook']):<12}"
            f"{_summary(report['probes']['trades']):<10}"
        )

    print("\nSummary")
    print(f"  ok:   {ok_count}")
    print(f"  fail: {err_count}")
    print(f"  mock: {mock_count}")

    out_dir = settings.absolute_path("data")
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"probe_xstocks_{utc_now_iso().replace(':', '-')}.json"
    path.write_text(
        json.dumps(
            {
                "generated_at": utc_now_iso(),
                "diagnostics": diag,
                "system_status": system_status,
                "summary": {"ok": ok_count, "fail": err_count, "mock": mock_count},
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"\nReport written to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
