"""Phase 26D — walk-forward verdict helpers for crowding overlay."""

from __future__ import annotations

from typing import Any, Literal, Mapping

from src.bot.crowding_overlay import compare_baseline_vs_overlay

Phase26Verdict = Literal[
    "kill",
    "blocked_data",
    "weak",
    "overlay_only",
    "validation_candidate",
    "paper_candidate_derivatives",
]

PHASE26_PAPER_CANDIDATE_DERIVATIVES_FORBIDDEN_LIVE = True
PHASE26_MICRO_LIVE = "NO-GO"

PHASE26_OVERLAY_STRATEGIES: tuple[tuple[str, str], ...] = (
    ("trend_following", "slow"),
    ("trend_following", "baseline"),
    ("ema_crossover", "baseline"),
    ("donchian_breakout", "baseline"),
)

PHASE26_ASSETS: tuple[str, ...] = ("BTC", "ETH")
PHASE26_TIMEFRAMES: tuple[str, ...] = ("4h", "1d")


def classify_phase26_overlay_verdict(
    baseline: Mapping[str, Any],
    overlay: Mapping[str, Any],
    *,
    wf_verdict: str = "weak",
) -> Phase26Verdict:
    if not baseline.get("data_ok") or not overlay.get("data_ok"):
        return "blocked_data"
    cmp = compare_baseline_vs_overlay(baseline, overlay)
    if cmp["improved_alpha"]:
        if wf_verdict in ("paper_candidate_walkforward", "paper_candidate"):
            return "paper_candidate_derivatives"
        if wf_verdict == "validation_candidate":
            return "validation_candidate"
        return "overlay_only"
    if cmp["improved_risk_only"]:
        return "overlay_only"
    if float(overlay.get("total_return_pct", 0)) < float(baseline.get("total_return_pct", 0)) - 3.0:
        return "kill"
    return "weak"


def summarize_phase26_walkforward(rows: list[dict[str, Any]]) -> dict[str, Any]:
    verdicts = [r.get("verdict", "weak") for r in rows if r.get("data_ok")]
    return {
        "runs_total": len(rows),
        "validation_candidate_count": sum(1 for v in verdicts if v == "validation_candidate"),
        "paper_candidate_derivatives_count": sum(
            1 for v in verdicts if v == "paper_candidate_derivatives"
        ),
        "overlay_only_count": sum(1 for v in verdicts if v == "overlay_only"),
        "weak_count": sum(1 for v in verdicts if v == "weak"),
        "kill_count": sum(1 for v in verdicts if v == "kill"),
        "blocked_data_count": sum(1 for r in rows if r.get("verdict") == "blocked_data"),
        "micro_live": PHASE26_MICRO_LIVE,
    }
