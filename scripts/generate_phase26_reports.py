#!/usr/bin/env python3
"""Generate Phase 26 markdown reports from JSON artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

READINESS = REPO_ROOT / "reports" / "data_manifests_phase26" / "derivatives_readiness.json"
EVENT_SUMMARY = REPO_ROOT / "reports" / "phase26_event_studies" / "summary.json"
OVERLAY_SUMMARY = REPO_ROOT / "reports" / "phase26_crowding_overlay" / "summary.json"
WF_SUMMARY = REPO_ROOT / "reports" / "phase26_walkforward" / "summary.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def generate_all(reports_dir: Path) -> None:
    readiness = _load(READINESS)
    events = _load(EVENT_SUMMARY)
    overlay = _load(OVERLAY_SUMMARY)
    wf = _load(WF_SUMMARY)

    (reports_dir / "PHASE26A_DATA_COLLECTORS.md").write_text(
        "\n".join(
            [
                "# Phase 26A — Derivatives data collectors",
                "",
                "Public-only Binance USDT-M endpoints (no API keys).",
                "",
                f"- Cache entries available: **{readiness.get('available_count', 0)}** / "
                f"{readiness.get('entries_total', 0)}",
                f"- Liquidations: **{readiness.get('liquidations', {}).get('status', 'blocked_data')}**",
                "",
                "## Sources",
                "",
                "- Funding: `fapi/v1/fundingRate`",
                "- Open interest: `futures/data/openInterestHist`",
                "- Liquidations: blocked — short rolling window only on Binance public API",
                "- OI history: Binance caps lookback (~30 days); use `--oi-days 30` on build script",
                "",
                "## Build",
                "",
                "```powershell",
                "python scripts/build_derivatives_cache_phase26.py --assets BTC ETH",
                "python scripts/audit_derivatives_cache_phase26.py",
                "```",
                "",
            ]
        ),
        encoding="utf-8",
    )

    bundles = events.get("bundles", [])
    (reports_dir / "PHASE26B_EVENT_STUDIES.md").write_text(
        "\n".join(
            [
                "# Phase 26B — Derivatives event studies",
                "",
                f"- Asset/timeframe bundles: **{len(bundles)}**",
                f"- Proceed to overlay gate: **{sum(1 for b in bundles if b.get('proceed_to_overlay'))}**",
                "",
                "## Hypotheses",
                "",
                "| Signal | Usage |",
                "|--------|-------|",
                "| funding_extreme | crowding longs/shorts |",
                "| funding_zscore | regime |",
                "| oi_expansion_flat_price | leverage accumulation |",
                "| oi_zscore_range_compress | squeeze setup |",
                "| liquidation_spike | blocked_data |",
                "| funding_oi_disagreement | contradiction |",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (reports_dir / "PHASE26C_OVERLAY_TOURNAMENT.md").write_text(
        "\n".join(
            [
                "# Phase 26C — Crowding overlay tournament",
                "",
                f"- Runs: **{overlay.get('runs_total', 0)}**",
                f"- overlay_only: **{overlay.get('overlay_only', 0)}**",
                f"- weak: **{overlay.get('weak', 0)}**",
                f"- validation_candidate: **{overlay.get('validation_candidate', 0)}**",
                f"- blocked_data: **{overlay.get('blocked_data', 0)}**",
                "",
                "Fees 40 bps, slippage 5 bps, cache-only.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (reports_dir / "RED_TEAM_PHASE26.md").write_text(
        "\n".join(
            [
                "# Red team — Phase 26",
                "",
                "1. **Single asset dominance?** Check ETH vs BTC overlay matrix.",
                "2. **Single period?** WF holdout windows must beat B&H on ≥2 slices.",
                "3. **Funding lookahead?** Alignment uses last funding at or before candle close.",
                "4. **OI alignment?** OI period matches timeframe (4h/1d); no future bar.",
                "5. **Overlay = risk only?** Compare return delta vs DD reduction in matrix.",
                "6. **Dangerous for micro-live?** Yes — derivatives research only; account blocked for xStocks.",
                "",
                "## Verdict",
                "",
                "Phase 26 is research-only. No live, no micro-live.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (reports_dir / "FINAL_QA_PHASE26.md").write_text(
        "\n".join(
            [
                "# Final QA — Phase 26",
                "",
                "## Collectors (26A)",
                f"- Readiness manifest present: **{READINESS.is_file()}**",
                "",
                "## Event studies (26B)",
                f"- Summary present: **{EVENT_SUMMARY.is_file()}**",
                "",
                "## Overlay (26C)",
                f"- Summary present: **{OVERLAY_SUMMARY.is_file()}**",
                "",
                "## Walk-forward (26D)",
                f"- Summary present: **{WF_SUMMARY.is_file()}**",
                f"- validation_candidate: **{wf.get('validation_candidate_count', 0)}**",
                f"- paper_candidate_derivatives: **{wf.get('paper_candidate_derivatives_count', 0)}**",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (reports_dir / "MICRO_LIVE_GO_NO_GO_PHASE26.md").write_text(
        "\n".join(
            [
                "# Micro-live GO/NO-GO — Phase 26",
                "",
                "## Verdict: **NO-GO**",
                "",
                "- Phase 26 scope is derivatives crowding research on Binance public feeds.",
                "- PEDSL-CY account cannot trade xStocks live; no new micro-live path.",
                "- `paper_candidate_derivatives` is a research label only — not armed for execution.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    vc = wf.get("validation_candidate_count", 0) + overlay.get("validation_candidate", 0)
    next_phase = (
        "Phase 27 — cross-venue basis / spot-perp spread research"
        if vc == 0
        else "Phase 27 — deepen overlay on validation_candidate cells only"
    )

    (reports_dir / "PHASE26_NEXT_DECISION.md").write_text(
        "\n".join(
            [
                "# Phase 26 — Next decision",
                "",
                f"- validation_candidate (combined): **{vc}**",
                f"- overlay_only: **{overlay.get('overlay_only', 0)}**",
                f"- Recommendation: **{next_phase}**",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (reports_dir / "PHASE26_DERIVATIVES_CROWDING_BLOCK.md").write_text(
        "\n".join(
            [
                "# Phase 26 — Derivatives crowding alpha block",
                "",
                "Tests whether funding + open interest add information beyond OHLCV alone.",
                "",
                "## Sub-phases",
                "",
                "- **26A** Public collectors + cache audit",
                "- **26B** Event studies (forward 4h/24h/72h)",
                "- **26C** Crowding overlay tournament on Phase 23 strategies",
                "- **26D** Walk-forward + red team",
                "",
                "## Allowed verdicts",
                "",
                "kill, blocked_data, weak, overlay_only, validation_candidate, "
                "paper_candidate_derivatives (research only).",
                "",
                "## Micro-live",
                "",
                "**NO-GO** — see `MICRO_LIVE_GO_NO_GO_PHASE26.md`.",
                "",
            ]
        ),
        encoding="utf-8",
    )


def main() -> int:
    p = argparse.ArgumentParser(description="Generate Phase 26 reports")
    p.add_argument("--reports-dir", type=Path, default=REPO_ROOT / "reports")
    args = p.parse_args()
    generate_all(args.reports_dir)
    print("Phase 26 reports written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
