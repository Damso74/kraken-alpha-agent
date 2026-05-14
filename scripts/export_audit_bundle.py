"""Export decisions / orders / PnL / config (without secrets) into export/."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_settings, safe_env_snapshot  # noqa: E402
from src.logger import setup_logging  # noqa: E402
from src.storage import (  # noqa: E402
    fetch_recent_decisions,
    fetch_recent_errors,
    fetch_recent_orders,
    fetch_recent_pnl,
)
from src.utils import utc_now_iso  # noqa: E402


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({k for r in rows for k in r.keys()})
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in keys})


def main() -> int:
    setup_logging()
    settings = get_settings()
    out_dir = settings.absolute_path("export") / utc_now_iso().replace(":", "-")
    out_dir.mkdir(parents=True, exist_ok=True)

    decisions = fetch_recent_decisions(limit=10_000)
    orders = fetch_recent_orders(limit=10_000)
    pnl = fetch_recent_pnl(limit=10_000)
    errors = fetch_recent_errors(limit=10_000)

    _write_json(out_dir / "decisions.json", decisions)
    _write_json(out_dir / "orders.json", orders)
    _write_json(out_dir / "pnl.json", pnl)
    _write_json(out_dir / "errors.json", errors)
    _write_json(
        out_dir / "config.json",
        {
            "competition": settings.config.competition.model_dump(),
            "trading": settings.config.trading.model_dump(),
            "universe": settings.config.universe.model_dump(),
            "strategy": settings.config.strategy.model_dump(),
            "risk": settings.config.risk.model_dump(),
            "execution": settings.config.execution.model_dump(),
            "dashboard": settings.config.dashboard.model_dump(),
            "env_snapshot_redacted": safe_env_snapshot(),
            "config_source": settings.config_source,
            "exported_at": utc_now_iso(),
        },
    )

    _write_csv(out_dir / "decisions.csv", decisions)
    _write_csv(out_dir / "orders.csv", orders)
    _write_csv(out_dir / "pnl.csv", pnl)

    print(f"Audit bundle written to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
