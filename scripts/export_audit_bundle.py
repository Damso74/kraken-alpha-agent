"""Export the agent's audit trail into ``export/<timestamp>/``.

What this bundle is for
-----------------------
The hackathon jury inspects the agent's behaviour end-to-end via:

1. ``kraken trades-history`` / ``kraken futures fills`` over a
   read-only Spot + Futures API key pair (the **canonical** PnL
   source — see ``docs/JURY_ACCESS_TEMPLATE.md``).
2. The local audit trail, which mirrors every decision, order, PnL
   snapshot, position update, cycle and error to ``data/agent.sqlite``
   + JSONL ledgers under ``data/``.

This script dumps a **secret-redacted** snapshot of (2) so the jury
can cross-check timestamps and order IDs against the Kraken history
without cloning the repo, the venv or the SQLite tooling. The dump
goes to ``export/<UTC-timestamp>/`` (a path that is ``.gitignore``'d
— the bundle is never committed; it is shared out-of-band per the
jury access template).

Safety properties
-----------------
- Strictly read-only against the database and the JSONL ledgers.
- Every payload goes through :func:`src.logger.mask_secrets` so any
  textual API key that ever leaked into a free-form field is
  scrubbed before reaching disk.
- The ``config.json`` block uses :func:`src.config.safe_env_snapshot`
  which only emits ``*_set`` booleans for credential env vars (the
  *presence* is reported, never the value).
- A ``README.md`` describing every file is written into the bundle
  so the jury never has to guess what each artefact contains.

The script is intentionally pure standard library plus the agent's
own ``src.*`` modules — no extra runtime dependency.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_settings, safe_env_snapshot  # noqa: E402
from src.logger import mask_secrets, setup_logging  # noqa: E402
from src.storage import (  # noqa: E402
    fetch_positions,
    fetch_recent_cycles,
    fetch_recent_decisions,
    fetch_recent_errors,
    fetch_recent_orders,
    fetch_recent_pnl,
)
from src.utils import utc_now_iso  # noqa: E402


def _redact(payload: Any) -> Any:
    """Recursively walk a JSON-shaped payload and mask any leaked secrets.

    The agent's structured fields already filter secrets at write time,
    but free-form ``message`` / ``rationale`` / ``where_label`` columns
    have ended up with key fragments in past incidents. Belt-and-
    suspenders : we run :func:`mask_secrets` on every string value
    *before* the bundle ever touches disk.
    """
    if isinstance(payload, str):
        return mask_secrets(payload)
    if isinstance(payload, dict):
        return {k: _redact(v) for k, v in payload.items()}
    if isinstance(payload, list):
        return [_redact(v) for v in payload]
    return payload


def _write_json(path: Path, payload: Any) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(_redact(payload), fh, ensure_ascii=False, indent=2)
    return path.stat().st_size


def _write_csv(path: Path, rows: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return 0
    rows = [_redact(r) for r in rows]
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in keys})
    return path.stat().st_size


def _mirror_jsonl(src: Path, dst: Path) -> int:
    """Copy a JSONL ledger line-by-line, masking secrets in each row."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not src.exists():
        dst.write_text("", encoding="utf-8")
        return 0
    written = 0
    with src.open("r", encoding="utf-8") as src_fh, dst.open(
        "w", encoding="utf-8"
    ) as dst_fh:
        for raw in src_fh:
            line = raw.rstrip("\n")
            if not line.strip():
                continue
            # JSONL lines are dicts in production; if parsing fails we
            # still pass the masked text through so the jury can see
            # the malformed row (rare but possible during VPS crashes).
            try:
                obj = json.loads(line)
                masked = _redact(obj)
                dst_fh.write(json.dumps(masked, ensure_ascii=False) + "\n")
            except json.JSONDecodeError:
                dst_fh.write(mask_secrets(line) + "\n")
            written += 1
    return written


def _write_readme(
    out_dir: Path,
    *,
    bundle_ts: str,
    counts: dict[str, int],
    file_sizes: dict[str, int],
) -> None:
    """Drop a README.md into the bundle so the jury sees a table of contents.

    Kept terse on purpose : the canonical narrative lives in
    ``docs/SUBMISSION.md`` + ``docs/JURY_ACCESS_TEMPLATE.md``; this
    file is a *manifest*, not a duplicate of the submission story.
    """
    lines: list[str] = [
        "# Audit bundle — Kraken Alpha Agent",
        "",
        f"- Generated at (UTC) : `{bundle_ts}`",
        "- Source : `data/agent.sqlite` (six tables) + `data/*.jsonl`",
        (
            "- Secret redaction : every string value passed through "
            "`src.logger.mask_secrets` before serialisation. Credentials "
            "are reported as booleans in `config.json` "
            "(`*_set` keys), never as plaintext."
        ),
        "",
        "## Files",
        "",
        "| File | Source table / ledger | Rows | Size (bytes) |",
        "|------|------------------------|------|--------------|",
    ]
    file_meta = [
        ("config.json", "active config + safe env snapshot", "1"),
        ("decisions.json", "`decisions` (SQLite)", str(counts.get("decisions", 0))),
        ("decisions.csv", "flat view of `decisions.json`", str(counts.get("decisions", 0))),
        ("orders.json", "`orders` (SQLite)", str(counts.get("orders", 0))),
        ("orders.csv", "flat view of `orders.json`", str(counts.get("orders", 0))),
        ("positions.json", "`positions` (SQLite)", str(counts.get("positions", 0))),
        ("pnl.json", "`pnl_snapshots` (SQLite)", str(counts.get("pnl", 0))),
        ("pnl.csv", "flat view of `pnl.json`", str(counts.get("pnl", 0))),
        ("cycles.json", "`cycles` (SQLite)", str(counts.get("cycles", 0))),
        ("errors.json", "`errors` (SQLite)", str(counts.get("errors", 0))),
        ("trades_jsonl_mirror.jsonl", "mirror of `data/trades.jsonl`", str(counts.get("trades_jsonl", 0))),
        ("decisions_jsonl_mirror.jsonl", "mirror of `data/decisions.jsonl`", str(counts.get("decisions_jsonl", 0))),
        ("pnl_jsonl_mirror.jsonl", "mirror of `data/pnl.jsonl`", str(counts.get("pnl_jsonl", 0))),
    ]
    for fname, source, count in file_meta:
        size = file_sizes.get(fname, 0)
        lines.append(f"| `{fname}` | {source} | {count} | {size:,} |")

    lines.extend(
        [
            "",
            "## Cross-referencing with Kraken's read-only audit",
            "",
            (
                "1. The jury fetches their live view via the read-only "
                "Spot + Futures API keys (`kraken trades-history`, "
                "`kraken futures fills`, `kraken balance`)."
            ),
            (
                "2. Every row in `orders.json` carries a `client_order_id` "
                "/ `kraken_order_id` field (when the order ever reached "
                "the venue). Cross-check the corresponding Kraken "
                "history entry by timestamp + symbol + size."
            ),
            (
                "3. PEDSL-CY-blocked attempts have an explicit `status` "
                "string (`blocked_venue_permission`, "
                "`status:wouldNotReducePosition`) and zero Kraken-side "
                "fill — see `docs/SUBMISSION.md` for the full diagnosis."
            ),
            "",
            "## Provenance reminder",
            "",
            (
                "This bundle is **read-only** : it never modifies the "
                "source DB or the JSONL ledgers. Re-run "
                "`python scripts/export_audit_bundle.py` at any time to "
                "produce a fresh dump under `export/<new-timestamp>/`."
            ),
        ]
    )
    out_dir.joinpath("README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    setup_logging()
    settings = get_settings()
    bundle_ts = utc_now_iso().replace(":", "-")
    out_dir = settings.absolute_path("export") / bundle_ts
    out_dir.mkdir(parents=True, exist_ok=True)

    decisions = fetch_recent_decisions(limit=10_000)
    orders = fetch_recent_orders(limit=10_000)
    pnl = fetch_recent_pnl(limit=10_000)
    errors = fetch_recent_errors(limit=10_000)
    positions = fetch_positions()
    cycles = fetch_recent_cycles(limit=10_000)

    file_sizes: dict[str, int] = {}
    file_sizes["config.json"] = _write_json(
        out_dir / "config.json",
        {
            "competition": settings.config.competition.model_dump(),
            "trading": settings.config.trading.model_dump(),
            "universe": settings.config.universe.model_dump(),
            "strategy": settings.config.strategy.model_dump(),
            "risk": settings.config.risk.model_dump(),
            "execution": settings.config.execution.model_dump(),
            "futures": settings.config.futures.model_dump(),
            "exit": settings.config.exit.model_dump(),
            "dashboard": settings.config.dashboard.model_dump(),
            "env_snapshot_redacted": safe_env_snapshot(),
            "config_source": settings.config_source,
            "active_profile": settings.active_profile,
            "available_profiles": settings.available_profiles,
            "exported_at": utc_now_iso(),
        },
    )

    file_sizes["decisions.json"] = _write_json(out_dir / "decisions.json", decisions)
    file_sizes["orders.json"] = _write_json(out_dir / "orders.json", orders)
    file_sizes["positions.json"] = _write_json(out_dir / "positions.json", positions)
    file_sizes["pnl.json"] = _write_json(out_dir / "pnl.json", pnl)
    file_sizes["cycles.json"] = _write_json(out_dir / "cycles.json", cycles)
    file_sizes["errors.json"] = _write_json(out_dir / "errors.json", errors)

    file_sizes["decisions.csv"] = _write_csv(out_dir / "decisions.csv", decisions)
    file_sizes["orders.csv"] = _write_csv(out_dir / "orders.csv", orders)
    file_sizes["pnl.csv"] = _write_csv(out_dir / "pnl.csv", pnl)

    # JSONL mirrors — these capture rows that may have been pruned out
    # of the SQLite tables (the agent rotates SQLite tables on disk-
    # pressure events; the JSONL ledgers are append-only and live
    # longer).
    data_dir = settings.absolute_path("data")
    trades_jsonl_rows = _mirror_jsonl(
        data_dir / "trades.jsonl", out_dir / "trades_jsonl_mirror.jsonl"
    )
    decisions_jsonl_rows = _mirror_jsonl(
        data_dir / "decisions.jsonl", out_dir / "decisions_jsonl_mirror.jsonl"
    )
    pnl_jsonl_rows = _mirror_jsonl(
        data_dir / "pnl.jsonl", out_dir / "pnl_jsonl_mirror.jsonl"
    )
    file_sizes["trades_jsonl_mirror.jsonl"] = (
        (out_dir / "trades_jsonl_mirror.jsonl").stat().st_size
    )
    file_sizes["decisions_jsonl_mirror.jsonl"] = (
        (out_dir / "decisions_jsonl_mirror.jsonl").stat().st_size
    )
    file_sizes["pnl_jsonl_mirror.jsonl"] = (
        (out_dir / "pnl_jsonl_mirror.jsonl").stat().st_size
    )

    counts = {
        "decisions": len(decisions),
        "orders": len(orders),
        "positions": len(positions),
        "pnl": len(pnl),
        "cycles": len(cycles),
        "errors": len(errors),
        "trades_jsonl": trades_jsonl_rows,
        "decisions_jsonl": decisions_jsonl_rows,
        "pnl_jsonl": pnl_jsonl_rows,
    }
    _write_readme(
        out_dir,
        bundle_ts=bundle_ts,
        counts=counts,
        file_sizes=file_sizes,
    )

    print(f"Audit bundle written to {out_dir}")
    print(
        "  rows: "
        + ", ".join(f"{k}={v}" for k, v in counts.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
