#!/usr/bin/env python3
"""Phase 27C — audit OI data depth and derivatives readiness."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.data.collectors.binance_basis_public import audit_basis_readiness  # noqa: E402
from src.data.collectors.binance_derivatives_public import (  # noqa: E402
    MAX_OI_LOOKBACK_DAYS,
    audit_derivatives_readiness,
    default_oi_cache_path,
    load_derivatives_cache,
)

DEFAULT_CACHE = REPO_ROOT / "data" / "collector_cache"
DEFAULT_OI_REPORT = REPO_ROOT / "reports" / "PHASE27_OI_DATA_DEPTH.md"
DEFAULT_MANIFEST = REPO_ROOT / "reports" / "data_manifests_phase27" / "derivatives_depth.json"

# Minimum rows for serious walk-forward (Phase 27 gate — OI excluded below this).
OI_WF_SERIOUS_MIN_ROWS = 500
OI_EXPERIMENTAL_LABEL = "experimental"


def _oi_span_days(rows: list[dict]) -> float:
    if len(rows) < 2:
        return 0.0
    ts0 = int(rows[0]["timestamp"])
    ts1 = int(rows[-1]["timestamp"])
    return max(0.0, (ts1 - ts0) / 86400.0)


def audit_oi_depth(
    assets: list[str],
    *,
    cache_root: Path,
    periods: tuple[str, ...] = ("4h", "1d"),
) -> dict:
    entries: list[dict] = []
    for asset in assets:
        sym = asset.upper().partition("/")[0]
        for period in periods:
            path = default_oi_cache_path(sym, period, cache_root)
            rows, meta = load_derivatives_cache(path)
            span = _oi_span_days(rows)
            wf_ok = len(rows) >= OI_WF_SERIOUS_MIN_ROWS and span >= 180
            entries.append(
                {
                    "asset": sym,
                    "period": period,
                    "path": str(path),
                    "row_count": len(rows),
                    "span_days": round(span, 1),
                    "binance_api_max_lookback_days": MAX_OI_LOOKBACK_DAYS,
                    "wf_serious": wf_ok,
                    "gate_status": "available" if rows else meta.get("status"),
                    "validation_candidate_eligible": wf_ok,
                    "label": "available" if wf_ok else OI_EXPERIMENTAL_LABEL,
                    "notes": (
                        "Binance openInterestHist ≈30d rolling window; "
                        "no longer public history without paid aggregator."
                    ),
                }
            )
    experimental = sum(1 for e in entries if e["label"] == OI_EXPERIMENTAL_LABEL)
    return {
        "generated_at": __import__(
            "src.data.collectors._common", fromlist=["utc_now_iso"]
        ).utc_now_iso(),
        "oi_wf_serious_min_rows": OI_WF_SERIOUS_MIN_ROWS,
        "entries": entries,
        "experimental_count": experimental,
        "coinglass_public": "not_integrated_requires_api_key",
        "recommendation": (
            "Keep OI experimental; exclude from validation_candidate gates until "
            "a documented long-history source is wired."
        ),
    }


def _write_md(report_path: Path, depth: dict, deriv: dict, basis: dict) -> None:
    lines = [
        "# Phase 27 — OI data depth audit",
        "",
        "## Verdict",
        "",
        f"- OI series labeled **{OI_EXPERIMENTAL_LABEL}** when row_count < {OI_WF_SERIOUS_MIN_ROWS} "
        f"or span < 180 days.",
        f"- Experimental OI entries: **{depth.get('experimental_count', 0)}**",
        "- Coinglass / paid aggregators: **not integrated** (API key required).",
        "- Binance `openInterestHist` API max lookback: **~30 days** (documented).",
        "",
        "## OI entries",
        "",
        "| asset | period | rows | span_days | label | validation_candidate |",
        "|-------|--------|------|-----------|-------|----------------------|",
    ]
    for e in depth.get("entries", []):
        lines.append(
            f"| {e['asset']} | {e['period']} | {e['row_count']} | {e['span_days']} | "
            f"{e['label']} | {e['validation_candidate_eligible']} |"
        )
    lines.extend(
        [
            "",
            "## Funding readiness (Phase 26 cache)",
            "",
            f"- available_count: **{deriv.get('available_count', 0)}**",
            "",
            "## Basis readiness (Phase 27 cache)",
            "",
            f"- available_count: **{basis.get('available_count', 0)}**",
            "",
            "## Recommendation",
            "",
            depth.get("recommendation", ""),
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="Audit Phase 27 derivatives data depth")
    p.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"])
    p.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE)
    p.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    p.add_argument("--report", type=Path, default=DEFAULT_OI_REPORT)
    args = p.parse_args()

    depth = audit_oi_depth(args.assets, cache_root=args.cache_root)
    deriv = audit_derivatives_readiness(args.assets, cache_dir=args.cache_root)
    basis = audit_basis_readiness(args.assets, cache_dir=args.cache_root)
    payload = {"oi_depth": depth, "derivatives": deriv, "basis": basis}
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_md(args.report, depth, deriv, basis)
    print(json.dumps({"experimental_count": depth["experimental_count"]}, indent=2))
    print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
