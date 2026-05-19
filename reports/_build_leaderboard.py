#!/usr/bin/env python3
"""Build ALPHA_RESEARCH_LEADERBOARD.{md,json} from research run JSON artifacts."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.research.cost_model import summarize_cost_assumptions
from src.research.tradeability import (
    LeaderboardEconomicOverlay,
    apply_economic_verdict_overlay,
    build_leaderboard_economic_overlay,
)

PHASE3 = {
    "runs_dir": REPO_ROOT / "reports" / "research_runs",
    "out_md": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD.md",
    "out_json": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD.json",
    "title": "Phase 3",
    "run_log": "reports/research_runs/RUN_LOG.md",
    "known_json": {
        "stablecoins_365d.json": {
            "signal": "stablecoin_supply_z_high",
            "dataset": "DefiLlama stablecoin supply + Kraken BTC OHLC",
            "period": "365d",
        },
        "calendar_730d.json": {
            "signal": "calendar_weekend_start",
            "dataset": "Kraken BTC OHLC (deterministic calendar)",
            "period": "730d",
        },
        "exchange_status_365d.json": {
            "signal": "exchange_status_major_incident",
            "dataset": "Kraken/Coinbase status pages + Kraken BTC OHLC",
            "period": "365d",
        },
        "demo_fng_180d.json": {
            "signal": "demo_fear_greed_extreme_fear",
            "dataset": "alternative.me F&G + Kraken BTC OHLC (demo harness)",
            "period": "180d",
            "is_demo": True,
        },
    },
    "blocked_rows": [
        {
            "signal": "wikipedia_btc_attention",
            "dataset": "Wikimedia pageviews REST + Kraken BTC OHLC",
            "period": "365d",
            "artifact": None,
            "rejection_reason": "HTTP 403 — Wikimedia requires User-Agent; no cache",
            "next_action": "Add compliant User-Agent in collector HTTP layer; re-run event_study_wikipedia.py",
        },
        {
            "signal": "eth_gas_congestion",
            "dataset": "Etherscan gas oracle/history + Kraken BTC OHLC",
            "period": "365d",
            "artifact": None,
            "rejection_reason": "Etherscan NOTOK; 0 daily gas history rows (need ETHERSCAN_API_KEY + history seed)",
            "next_action": "Set ETHERSCAN_API_KEY; seed etherscan_gas_history.json; re-run event_study_eth_gas.py",
        },
    ],
    "summary_blocked_note": "Wikipedia (403), ETH gas (no Etherscan history).",
    "verdict_rules": "phase3",
}

PHASE11 = {
    "runs_dir": REPO_ROOT / "reports" / "research_runs_phase11",
    "out_md": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD_PHASE11.md",
    "out_json": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD_PHASE11.json",
    "compare_md": REPO_ROOT / "reports" / "PHASE_6_VS_PHASE11.md",
    "title": "Phase 11",
    "run_log": "reports/research_runs_phase11/RUN_LOG_PHASE11.md",
    "v2_json": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD_V2.json",
}

PHASE11_ALLOWED_VERDICTS = frozenset(
    {
        "kill",
        "blocked",
        "not supported",
        "weak evidence",
        "retry with fixed data",
        "candidate for further OOS testing",
    }
)

PHASE11_RED_TEAM_DOC = REPO_ROOT / "reports" / "RED_TEAM_PHASE11.md"

# Statuts red team qui interdisent toute promotion OOS (règle explicite Phase 11).
PHASE11_RED_TEAM_BLOCKS_OOS = frozenset({"fail", "revoked", "révoqué", "révoque"})

CALENDAR_HYPOTHESIS_IDS: dict[str, str] = {
    "us_market_open_window": "P9-CA-032",
    "sunday_us_evening": "P9-CAL-SUN-US",
    "monday_asia_open": "P9-CAL-MON-ASIA",
    "third_friday": "P9-CA-037",
    "month_end": "P9-CAL-MONTH-END",
}

PHASE6 = {
    "runs_dir": REPO_ROOT / "reports" / "research_runs_v2",
    "out_md": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD_V2.md",
    "out_json": REPO_ROOT / "reports" / "ALPHA_RESEARCH_LEADERBOARD_V2.json",
    "title": "Phase 6",
    "run_log": "reports/research_runs_v2/RUN_LOG_V2.md",
    "known_json": {
        "stablecoins_365d.json": {
            "signal": "stablecoin_supply_z_high",
            "dataset": "DefiLlama stablecoin supply + Binance public BTC OHLC",
            "period": "365d",
        },
        "wikipedia_365d.json": {
            "signal": "wikipedia_btc_attention",
            "dataset": "Wikimedia pageviews REST + Binance public BTC OHLC",
            "period": "365d",
        },
        "calendar_730d.json": {
            "signal": "calendar_weekend_start",
            "dataset": "Binance public BTC OHLC (deterministic calendar)",
            "period": "730d",
        },
        "exchange_status_365d.json": {
            "signal": "exchange_status_major_incident",
            "dataset": "Kraken/Coinbase status pages + Binance public BTC OHLC",
            "period": "365d",
        },
        "demo_fng_365d.json": {
            "signal": "demo_fear_greed_extreme_fear",
            "dataset": "alternative.me F&G + Kraken BTC OHLC (demo harness)",
            "period": "365d",
            "is_demo": True,
        },
    },
    "blocked_rows": [
        {
            "signal": "eth_gas_congestion",
            "dataset": "Etherscan gas history cache + Binance public BTC OHLC",
            "period": "365d",
            "artifact": None,
            "rejection_reason": "etherscan_gas_history.json absent (<181 daily rows required)",
            "next_action": "Set ETHERSCAN_API_KEY; seed etherscan_gas_history.json; re-run event_study_eth_gas.py",
        },
    ],
    "summary_blocked_note": "ETH gas (no history cache).",
    "verdict_rules": "phase6",
}


@dataclass
class LeaderboardRow:
    signal: str
    dataset: str
    period: str
    nb_events: int | None
    nb_cells_tested: int | None
    nb_cells_bh_rejected: int | None
    best_corrected_p: float | None
    best_raw_p: float | None
    placebo_status: str
    verdict: str
    rejection_reason: str | None
    next_action: str
    artifact: str | None
    script_verdict: str | None = None
    gross_avg_return_pct: float | None = None
    round_trip_cost_pct: float | None = None
    net_avg_return_pct: float | None = None
    turnover_proxy: float | None = None
    cost_dominated: bool | None = None
    tradeability_verdict: str | None = None
    economic_reject: bool | None = None
    economic_reject_reason: str | None = None
    reference_cell: str | None = None
    concentration_verdict: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _min_finite(values: list[float]) -> float | None:
    finite = [v for v in values if isinstance(v, (int, float)) and math.isfinite(v)]
    return min(finite) if finite else None


def _placebo_status(report: dict[str, Any]) -> str:
    n_placebos = report.get("n_placebos")
    cells = report.get("cells") or []
    if not cells:
        return "not run (0 testable cells)"
    if n_placebos:
        return f"random-events bootstrap ({n_placebos} reps); empirical two-sided p"
    return "unknown"


def _strict_verdict_phase3(
    *,
    blocked: bool,
    nb_events: int,
    nb_cells_bh_rejected: int,
    nb_cells_tested: int,
    is_demo: bool = False,
) -> tuple[str, str | None]:
    if blocked:
        return "blocked", "Incomplete dataset / API or cache failure"

    if nb_cells_tested == 0:
        return (
            "weak evidence",
            "Zero aligned events — hypothesis not exercised on this window",
        )

    if nb_cells_bh_rejected == 0:
        return "not supported, move on", None

    if nb_events < 10:
        return (
            "weak evidence",
            f"BH rejects {nb_cells_bh_rejected} cell(s) but only {nb_events} events (<10)",
        )

    if is_demo:
        return (
            "weak evidence",
            "Demo harness only — BH rejections not promoted to OOS candidate",
        )

    return (
        "candidate for OOS retest",
        None,
    )


def _strict_verdict_phase6(
    *,
    blocked: bool,
    nb_events: int,
    nb_cells_bh_rejected: int,
    nb_cells_tested: int,
    raw_ps: list[float],
    is_demo: bool = False,
    script_verdict: str | None = None,
) -> tuple[str, str | None]:
    if blocked:
        return "blocked", "Incomplete dataset / API or cache failure"

    if nb_events == 0 or (
        script_verdict and script_verdict.startswith("blocked")
    ):
        return "blocked", "insufficient events (zero aligned on window)"

    if nb_events < 5:
        return (
            "weak evidence",
            f"Only {nb_events} aligned events — underpowered for inference",
        )

    if nb_cells_bh_rejected == 0:
        if any(p < 0.05 for p in raw_ps):
            return (
                "weak evidence",
                "Raw p<0.05 on some cells but BH FDR rejects nothing",
            )
        return "not supported, move on", None

    if nb_events < 10 or is_demo:
        reason = (
            "Demo harness only — BH rejections not promoted to OOS candidate"
            if is_demo
            else f"BH rejects {nb_cells_bh_rejected} cell(s) but only {nb_events} events (<10)"
        )
        return "weak evidence", reason

    return (
        "candidate for OOS retest",
        None,
    )


def _next_action_default(
    verdict: str,
    signal: str,
    report: dict[str, Any] | None,
    *,
    run_log: str,
    rejection_reason: str | None = None,
) -> str:
    if verdict == "blocked":
        if report is not None and int(report.get("events_count") or 0) == 0:
            if "insufficient events" in (rejection_reason or ""):
                return (
                    "Lower z-threshold or widen lookback; see RUN_LOG probe notes — "
                    "not weak evidence until events exist"
                )
        return f"Unblock data source per {run_log}, then re-run event study"
    if verdict == "not supported, move on":
        return "Archive hypothesis; do not allocate OOS or live capital"
    if verdict == "weak evidence":
        if report and report.get("events_count", 0) == 0:
            return "Lower z-threshold or widen window; re-run stablecoin study if still relevant"
        if report and report.get("events_count", 0) < 10:
            return "Widen incident window or lower min_impact only if hypothesis allows; else move on"
        if signal.startswith("demo_"):
            return "Re-run on full event_study harness across assets/windows before any OOS"
        return "Gather more events or refine conditioning; no trading claim"
    if verdict == "candidate for OOS retest":
        return "Hold-out / walk-forward on unseen window and additional assets; still not live-ready"
    return f"Review {run_log}"


def _apply_economic_overlay(
    row: LeaderboardRow,
    overlay: LeaderboardEconomicOverlay,
    *,
    run_log: str,
) -> LeaderboardRow:
    verdict, rejection_reason = apply_economic_verdict_overlay(
        row.verdict,
        row.rejection_reason,
        overlay,
    )
    next_action = _next_action_default(
        verdict,
        row.signal,
        None,
        run_log=run_log,
        rejection_reason=rejection_reason,
    )
    return LeaderboardRow(
        signal=row.signal,
        dataset=row.dataset,
        period=row.period,
        nb_events=row.nb_events,
        nb_cells_tested=row.nb_cells_tested,
        nb_cells_bh_rejected=row.nb_cells_bh_rejected,
        best_corrected_p=row.best_corrected_p,
        best_raw_p=row.best_raw_p,
        placebo_status=row.placebo_status,
        verdict=verdict,
        rejection_reason=rejection_reason,
        next_action=next_action,
        artifact=row.artifact,
        script_verdict=row.script_verdict,
        gross_avg_return_pct=overlay.gross_avg_return_pct,
        round_trip_cost_pct=overlay.round_trip_cost_pct,
        net_avg_return_pct=overlay.net_avg_return_pct,
        turnover_proxy=overlay.turnover_proxy,
        cost_dominated=overlay.cost_dominated,
        tradeability_verdict=overlay.tradeability_verdict,
        economic_reject=overlay.economic_reject,
        economic_reject_reason=overlay.economic_reject_reason,
        reference_cell=overlay.reference_cell,
        concentration_verdict=overlay.concentration_verdict,
    )


def row_from_json(
    name: str,
    meta: dict[str, Any],
    report: dict[str, Any],
    *,
    runs_rel: str,
    run_log: str,
    verdict_rules: str,
) -> LeaderboardRow:
    cells = report.get("cells") or []
    bh_rejected = int(report.get("bh_rejected") or 0)
    q_values = report.get("bh_q_values") or []
    raw_ps = [float(c["two_sided_p"]) for c in cells if "two_sided_p" in c]
    nb_events = int(report.get("events_count") or report.get("events_used") or 0)
    nb_cells = len(cells)
    script_verdict = report.get("verdict")

    best_q = _min_finite([float(q) for q in q_values]) if q_values else None
    best_raw = _min_finite(raw_ps)
    best_corrected = best_q if q_values else best_raw

    if verdict_rules == "phase6":
        verdict, rejection_reason = _strict_verdict_phase6(
            blocked=False,
            nb_events=nb_events,
            nb_cells_bh_rejected=bh_rejected,
            nb_cells_tested=nb_cells,
            raw_ps=raw_ps,
            is_demo=bool(meta.get("is_demo")),
            script_verdict=str(script_verdict) if script_verdict else None,
        )
    else:
        verdict, rejection_reason = _strict_verdict_phase3(
            blocked=False,
            nb_events=nb_events,
            nb_cells_bh_rejected=bh_rejected,
            nb_cells_tested=nb_cells,
            is_demo=bool(meta.get("is_demo")),
        )

    return LeaderboardRow(
        signal=str(meta["signal"]),
        dataset=str(meta["dataset"]),
        period=str(meta["period"]),
        nb_events=nb_events,
        nb_cells_tested=nb_cells,
        nb_cells_bh_rejected=bh_rejected,
        best_corrected_p=best_corrected,
        best_raw_p=best_raw,
        placebo_status=_placebo_status(report),
        verdict=verdict,
        rejection_reason=rejection_reason,
        next_action=_next_action_default(
            verdict,
            str(meta["signal"]),
            report,
            run_log=run_log,
            rejection_reason=rejection_reason,
        ),
        artifact=f"{runs_rel}/{name}",
        script_verdict=script_verdict,
    )


def row_from_json_with_economics(
    name: str,
    meta: dict[str, Any],
    report: dict[str, Any],
    *,
    runs_rel: str,
    run_log: str,
    verdict_rules: str,
) -> LeaderboardRow:
    row = row_from_json(
        name,
        meta,
        report,
        runs_rel=runs_rel,
        run_log=run_log,
        verdict_rules=verdict_rules,
    )
    bh_supported = int(report.get("bh_rejected") or 0) > 0
    overlay = build_leaderboard_economic_overlay(
        report,
        bh_supported=bh_supported,
        oos_confirmed=False,
    )
    return _apply_economic_overlay(row, overlay, run_log=run_log)


def row_from_blocked(entry: dict[str, Any]) -> LeaderboardRow:
    verdict = "blocked"
    return LeaderboardRow(
        signal=entry["signal"],
        dataset=entry["dataset"],
        period=entry["period"],
        nb_events=None,
        nb_cells_tested=None,
        nb_cells_bh_rejected=None,
        best_corrected_p=None,
        best_raw_p=None,
        placebo_status="not run",
        verdict=verdict,
        rejection_reason=entry["rejection_reason"],
        next_action=entry["next_action"],
        artifact=entry.get("artifact"),
        script_verdict=None,
    )


def build_rows(phase: dict[str, Any]) -> list[LeaderboardRow]:
    runs_dir: Path = phase["runs_dir"]
    runs_rel = str(runs_dir.relative_to(REPO_ROOT)).replace("\\", "/")
    use_economics = phase.get("verdict_rules") == "phase6"
    rows: list[LeaderboardRow] = []
    for name, meta in phase["known_json"].items():
        path = runs_dir / name
        if not path.is_file():
            continue
        report = json.loads(path.read_text(encoding="utf-8"))
        if use_economics:
            rows.append(
                row_from_json_with_economics(
                    name,
                    meta,
                    report,
                    runs_rel=runs_rel,
                    run_log=phase["run_log"],
                    verdict_rules=phase["verdict_rules"],
                )
            )
        else:
            rows.append(
                row_from_json(
                    name,
                    meta,
                    report,
                    runs_rel=runs_rel,
                    run_log=phase["run_log"],
                    verdict_rules=phase["verdict_rules"],
                )
            )
    for entry in phase["blocked_rows"]:
        rows.append(row_from_blocked(entry))
    return rows


def _fmt_p(value: float | None) -> str:
    if value is None:
        return "—"
    if not math.isfinite(value):
        return "—"
    return f"{value:.4g}"


def _fmt_pct(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value * 100:.2f}%"


def _fmt_turnover(value: float | None) -> str:
    if value is None or not math.isfinite(value):
        return "—"
    return f"{value:.3f}"


def _fmt_yes_no(value: bool | None) -> str:
    if value is None:
        return "—"
    return "yes" if value else "no"


@dataclass
class Phase11LeaderboardRow:
    signal: str
    hypothesis_id: str
    dataset: str
    events: int | None
    bh_rejected: int | None
    bh_cells_total: int | None
    placebo: str
    cost_verdict: str
    regime_verdict: str
    concentration_verdict: str
    red_team_status: str
    final_verdict: str
    next_action: str
    artifact: str
    rejection_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_phase11_verdict(raw: str | None) -> str:
    """Map script/legacy verdict strings to Phase 11 allowed set."""
    if not raw:
        return "kill"
    stripped = raw.strip()
    if stripped in PHASE11_ALLOWED_VERDICTS:
        return stripped
    s = stripped.lower()
    if "blocked" in s or s == "blocked: insufficient events":
        return "blocked"
    if "not supported" in s:
        return "not supported"
    if "weak" in s:
        return "weak evidence"
    if "retry" in s or "fixed data" in s:
        return "retry with fixed data"
    if "candidate" in s or "oos" in s:
        return "candidate for further OOS testing"
    if s in ("kill", "killed"):
        return "kill"
    if s == "supported":
        return "weak evidence"
    return "kill"


def cost_verdict_from_overlay(overlay: LeaderboardEconomicOverlay | None) -> str:
    if overlay is None or overlay.tradeability_verdict is None:
        return "non évalué"
    tv = overlay.tradeability_verdict
    if tv == "economically impossible":
        return "échec (seuil brut suspect)"
    if tv == "cost dominated":
        return "dominé par coûts"
    if tv == "research only":
        return "marginal (recherche uniquement)"
    if tv == "candidate for paper observation":
        return "passage coûts (observation papier)"
    return "non évalué"


def _finalize_phase11_verdict(
    script_verdict: str,
    overlay: LeaderboardEconomicOverlay | None,
    *,
    cap_candidate_with_economics: bool = True,
) -> tuple[str, str | None]:
    verdict = normalize_phase11_verdict(script_verdict)
    reason: str | None = None
    if overlay and overlay.economic_reject_reason:
        reason = overlay.economic_reject_reason
    if (
        cap_candidate_with_economics
        and overlay
        and overlay.economic_reject
        and verdict == "candidate for further OOS testing"
    ):
        verdict = "weak evidence"
        reason = reason or "portes économiques (retour) non passées"
    return verdict, reason


def lookup_phase11_red_team_status(signal: str, hypothesis_id: str) -> str:
    """Statut red team par signal (synthèse RED_TEAM_PHASE11.md, 2026-05-19)."""
    if signal.startswith("wikipedia_"):
        return "revoked"
    if signal == "calendar_us_market_open_window":
        return "warning"
    if signal.startswith("calendar_"):
        return "fail"
    if signal.startswith("volume_shock_"):
        return "fail"
    if signal.startswith("exchange_status_"):
        return "fail"
    if signal.startswith("stablecoin_"):
        return "fail"
    if hypothesis_id.startswith("P9-"):
        return "fail"
    return "fail"


def apply_red_team_final_cap(
    final_verdict: str,
    red_team_status: str,
    *,
    rejection_reason: str | None = None,
) -> tuple[str, str | None]:
    """Si red_team_status est fail/revoked, final_verdict ne peut pas être candidat OOS."""
    rt = red_team_status.strip().lower()
    if rt not in PHASE11_RED_TEAM_BLOCKS_OOS:
        return final_verdict, rejection_reason
    if final_verdict != "candidate for further OOS testing":
        return final_verdict, rejection_reason
    extra = (
        "revoked_by_red_team (RED_TEAM_PHASE11.md)"
        if rt == "revoked"
        else "rétrogradé par red team FAIL (RED_TEAM_PHASE11.md)"
    )
    reason = f"{rejection_reason}; {extra}" if rejection_reason else extra
    return "weak evidence", reason


def apply_phase11_red_team_row(row: Phase11LeaderboardRow) -> Phase11LeaderboardRow:
    red_team = lookup_phase11_red_team_status(row.signal, row.hypothesis_id)
    final_v, reason = apply_red_team_final_cap(
        row.final_verdict,
        red_team,
        rejection_reason=row.rejection_reason,
    )
    if red_team == "revoked":
        tag = "revoked_by_red_team (RED_TEAM_PHASE11.md)"
        if tag not in (reason or ""):
            reason = f"{reason}; {tag}" if reason else tag
        if final_v == "candidate for further OOS testing":
            final_v = "weak evidence"
    next_action = _phase11_next_action(
        final_v,
        signal=row.signal,
        hypothesis_id=row.hypothesis_id,
        rejection_reason=reason,
    )
    return Phase11LeaderboardRow(
        signal=row.signal,
        hypothesis_id=row.hypothesis_id,
        dataset=row.dataset,
        events=row.events,
        bh_rejected=row.bh_rejected,
        bh_cells_total=row.bh_cells_total,
        placebo=row.placebo,
        cost_verdict=row.cost_verdict,
        regime_verdict=row.regime_verdict,
        concentration_verdict=row.concentration_verdict,
        red_team_status=red_team,
        final_verdict=final_v,
        next_action=next_action,
        artifact=row.artifact,
        rejection_reason=reason,
    )


def _phase11_next_action(
    verdict: str,
    *,
    signal: str,
    hypothesis_id: str,
    rejection_reason: str | None = None,
) -> str:
    if verdict == "candidate for further OOS testing":
        return (
            f"Tenir {hypothesis_id} en file OOS (fenêtre et actifs non vus) ; "
            "reproduire placebos shift/lag ; jamais capital live."
        )
    if verdict == "blocked":
        if "0 event" in (rejection_reason or "").lower() or signal.endswith("_compression"):
            return "Revoir seuils pré-enregistrés ou fenêtre ; pas de promotion sans événements alignés."
        return "Débloquer source/cache (voir RUN_LOG_PHASE11) puis relancer le harness."
    if verdict == "retry with fixed data":
        return "Corriger collecteur/cache/API puis relancer l’étude avec seuils figés."
    if verdict == "not supported":
        return "Archiver l’hypothèse ; ne pas allouer d’OOS ni de capital."
    if verdict == "weak evidence":
        if "revoked_by_red_team" in (rejection_reason or "").lower():
            return (
                "Archiver toute promotion OOS ; aligner sur RED_TEAM_PHASE11.md ; "
                "hold-out explicite requis avant toute re-évaluation."
            )
        if "placebo" in (rejection_reason or "").lower():
            return "Traiter comme artefact de calendrier/timing ; ne pas promouvoir sans batterie placebo complète."
        return "Conserver en recherche descriptive ; pas de revendication trading."
    if verdict == "kill":
        return "Clôturer la variante ; documenter dans le backlog Phase 12 si besoin."
    return f"Revoir {PHASE11['run_log']} et l’artifact JSON associé."


def _bh_summary(report: dict[str, Any]) -> tuple[int, int]:
    cells = report.get("cells") or []
    bh = int(report.get("bh_rejected") or 0)
    return bh, len(cells)


def _overlay_for_report(report: dict[str, Any]) -> LeaderboardEconomicOverlay:
    bh, _ = _bh_summary(report)
    return build_leaderboard_economic_overlay(
        report,
        bh_supported=bh > 0,
        oos_confirmed=False,
    )


def _rows_from_calendar(path: Path, runs_rel: str) -> list[Phase11LeaderboardRow]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows: list[Phase11LeaderboardRow] = []
    for effect in doc.get("effects") or []:
        effect_id = str(effect["effect_id"])
        signal = f"calendar_{effect_id}"
        hypo_id = CALENDAR_HYPOTHESIS_IDS.get(effect_id, f"P9-CAL-{effect_id}")
        overlay_dict = effect.get("economic_overlay") or {}
        overlay = LeaderboardEconomicOverlay(
            gross_avg_return_pct=overlay_dict.get("gross_avg_return_pct"),
            round_trip_cost_pct=overlay_dict.get("round_trip_cost_pct"),
            net_avg_return_pct=overlay_dict.get("net_avg_return_pct"),
            turnover_proxy=overlay_dict.get("turnover_proxy"),
            cost_dominated=bool(overlay_dict.get("cost_dominated")),
            tradeability_verdict=overlay_dict.get("tradeability_verdict"),
            economic_reject=bool(overlay_dict.get("economic_reject")),
            economic_reject_reason=overlay_dict.get("economic_reject_reason"),
            reference_cell=overlay_dict.get("reference_cell"),
            concentration_verdict=overlay_dict.get("concentration_verdict") or "not_assessed",
        )
        script_v = str(effect.get("verdict") or doc.get("verdict_summary", {}).get(effect_id, "kill"))
        final_v, reason = _finalize_phase11_verdict(script_v, overlay)
        if effect.get("rejection_reason") and not reason:
            reason = str(effect["rejection_reason"])
        bh, n_cells = _bh_summary(effect)
        sw_p = effect.get("placebo_same_weekday_return_post_7_p")
        sh_p = effect.get("placebo_shifted_calendar_return_post_7_p")
        placebo = (
            f"bootstrap {effect.get('n_placebos', 200)} ; "
            f"same-weekday post_7 p={_fmt_p(sw_p) if sw_p is not None else '—'} ; "
            f"shift +14..60d post_7 p={_fmt_p(sh_p) if sh_p is not None else '—'}"
        )
        rows.append(
            Phase11LeaderboardRow(
                signal=signal,
                hypothesis_id=hypo_id,
                dataset=f"Kraken/Binance cache BTC OHLC + calendrier déterministe ({doc.get('window_days')}j)",
                events=int(effect.get("events_used") or effect.get("events_count") or 0),
                bh_rejected=bh,
                bh_cells_total=n_cells,
                placebo=placebo,
                cost_verdict=cost_verdict_from_overlay(overlay),
                regime_verdict=f"calendrier fixe ({effect_id})",
                concentration_verdict=str(overlay.concentration_verdict or "not_assessed"),
                red_team_status=lookup_phase11_red_team_status(signal, hypo_id),
                final_verdict=final_v,
                next_action=_phase11_next_action(
                    final_v,
                    signal=signal,
                    hypothesis_id=hypo_id,
                    rejection_reason=reason,
                ),
                artifact=f"{runs_rel}/calendar_micro_baselines.json#{effect_id}",
                rejection_reason=reason,
            )
        )
    return rows


def _rows_from_volume_shock(path: Path, runs_rel: str) -> list[Phase11LeaderboardRow]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows: list[Phase11LeaderboardRow] = []
    for variant_id, block in (doc.get("variants") or {}).items():
        signal = f"volume_shock_{variant_id}"
        events = int(block.get("events_used") or block.get("events_count") or 0)
        bh, n_cells = _bh_summary(block)
        overlay = _overlay_for_report(block) if block.get("cells") else None
        script_v = str(block.get("research_verdict") or block.get("verdict") or "kill")
        final_v, reason = _finalize_phase11_verdict(script_v, overlay)
        placebos = block.get("placebos") or {}
        shift_p = placebos.get("shift_return_post_3_p")
        shuffle_p = placebos.get("shuffle_labels_return_post_3_p")
        placebo = (
            f"bootstrap {placebos.get('random_dates_bootstrap_n', 200)} ; "
            f"shift +30j post_3 p={_fmt_p(shift_p) if shift_p is not None else '—'} ; "
            f"shuffle labels post_3 p={_fmt_p(shuffle_p) if shuffle_p is not None else '—'}"
        )
        if shift_p == 1.0 and final_v == "weak evidence":
            extra = "placebos shift/shuffle non passés"
            reason = f"{reason}; {extra}" if reason else extra
        rows.append(
            Phase11LeaderboardRow(
                signal=signal,
                hypothesis_id="P9-MS-023",
                dataset="BTC OHLC journalier (cache) — choc volume z pré-enregistré",
                events=events,
                bh_rejected=bh,
                bh_cells_total=n_cells,
                placebo=placebo,
                cost_verdict=cost_verdict_from_overlay(overlay),
                regime_verdict="non évalué",
                concentration_verdict=overlay.concentration_verdict if overlay else "not_assessed",
                red_team_status="en attente (Agent 32)",
                final_verdict=final_v,
                next_action=_phase11_next_action(
                    final_v,
                    signal=signal,
                    hypothesis_id="P9-MS-023",
                    rejection_reason=reason,
                ),
                artifact=f"{runs_rel}/volume_shock_all_365d.json#{variant_id}",
                rejection_reason=reason,
            )
        )
    return rows


def _rows_from_wikipedia(path: Path, runs_rel: str) -> list[Phase11LeaderboardRow]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows: list[Phase11LeaderboardRow] = []
    for key, block in (doc.get("thresholds") or {}).items():
        z = block.get("z_threshold", key)
        signal = f"wikipedia_crypto_basket_z{z}"
        events = int(block.get("events_used") or block.get("events_count") or 0)
        bh, n_cells = _bh_summary(block)
        overlay = _overlay_for_report(block)
        script_v = str(block.get("phase11_verdict") or doc.get("phase11_final_verdict") or "kill")
        final_v, reason = _finalize_phase11_verdict(script_v, overlay)
        cost_v = "H1 vol/volume (retour secondaire)"
        if overlay and overlay.tradeability_verdict:
            cost_v = f"{cost_v} ; overlay retour={overlay.tradeability_verdict}"
        pb = block.get("placebos") or {}
        placebo = (
            f"bootstrap {pb.get('random_events_bootstrap', {}).get('n_placebos', 200)} ; "
            f"shift +30j vol sig={pb.get('shift_30d_vol_heuristic_significant')} ; "
            f"placebo non-crypto vol sig={pb.get('non_crypto_basket_vol_heuristic_significant')}"
        )
        rows.append(
            Phase11LeaderboardRow(
                signal=signal,
                hypothesis_id="P9-AT-012",
                dataset="Wikimedia pageviews (panier 8 pages crypto) + BTC OHLC cache 365j",
                events=events,
                bh_rejected=bh,
                bh_cells_total=n_cells,
                placebo=placebo,
                cost_verdict=cost_v,
                regime_verdict="non évalué",
                concentration_verdict=overlay.concentration_verdict or "not_assessed",
                red_team_status="en attente (Agent 32)",
                final_verdict=final_v,
                next_action=_phase11_next_action(
                    final_v,
                    signal=signal,
                    hypothesis_id="P9-AT-012",
                    rejection_reason=reason,
                ),
                artifact=f"{runs_rel}/wikipedia_basket_365d.json#z{z}",
                rejection_reason=reason,
            )
        )
    return rows


def _rows_from_stablecoin_file(path: Path, runs_rel: str) -> list[Phase11LeaderboardRow]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    hypo_id = str(doc.get("preregistration_id") or path.stem)
    btc = (doc.get("tickers") or {}).get("BTC") or {}
    events = int(doc.get("events_count_aligned_btc") or doc.get("events_count_raw") or 0)
    bh = int(btc.get("bh_rejected") or 0)
    n_cells = len(btc.get("cells") or [])
    overlay = _overlay_for_report({**btc, "events_count": events, "candles_count": btc.get("candles_count")})
    script_v = str(doc.get("verdict") or "kill")
    if events == 0 and "blocked" in script_v:
        final_v = "blocked"
        reason = "0 événement aligné sur la fenêtre"
    else:
        final_v, reason = _finalize_phase11_verdict(script_v, overlay)
    pb = doc.get("placebos") or {}
    placebo_pass = pb.get("placebo_pass")
    placebo = (
        f"bootstrap {pb.get('random_bootstrap', {}).get('n_replicates', 200)} "
        f"pass={pb.get('random_bootstrap', {}).get('pass')} ; "
        f"shift 30j pass={pb.get('shift_30d', {}).get('pass')} ; "
        f"lag inversé pass={pb.get('wrong_direction_lag', {}).get('pass')} ; "
        f"batterie globale pass={placebo_pass}"
    )
    if placebo_pass is False and final_v == "candidate for further OOS testing":
        final_v = "weak evidence"
        extra = "batterie placebo Phase 11 non passée"
        reason = f"{reason}; {extra}" if reason else extra
    thr = doc.get("pre_registered_threshold") or {}
    signal = (
        f"stablecoin_{thr.get('metric', 'supply')}_{thr.get('supply_lag_days')}d_"
        f"{thr.get('direction', 'na')}"
    )
    return [
        Phase11LeaderboardRow(
            signal=signal,
            hypothesis_id=hypo_id,
            dataset="DefiLlama stablecoin supply + BTC/ETH OHLC cache 365j",
            events=events,
            bh_rejected=bh,
            bh_cells_total=n_cells,
            placebo=placebo,
            cost_verdict=cost_verdict_from_overlay(overlay),
            regime_verdict="non évalué",
            concentration_verdict=overlay.concentration_verdict or "not_assessed",
            red_team_status="en attente (Agent 32)",
            final_verdict=normalize_phase11_verdict(final_v),
            next_action=_phase11_next_action(
                normalize_phase11_verdict(final_v),
                signal=signal,
                hypothesis_id=hypo_id,
                rejection_reason=reason,
            ),
            artifact=f"{runs_rel}/{path.name}",
            rejection_reason=reason,
        )
    ]


def _rows_from_exchange_deep_dive(path: Path, runs_rel: str) -> list[Phase11LeaderboardRow]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    rows: list[Phase11LeaderboardRow] = []
    for variant in doc.get("variants") or []:
        diag = variant.get("diagnostics") or {}
        variant_id = str(diag.get("variant_id") or "unknown")
        signal = f"exchange_status_{variant_id}"
        events = int(diag.get("aligned_events") or 0)
        primary = (variant.get("primary") or {}).get("report") or {}
        secondary = (variant.get("secondary") or {}).get("report") or {}
        bh_p = int(primary.get("bh_rejected") or 0)
        n_cells = len(primary.get("cells") or []) + len(secondary.get("cells") or [])
        overlay = _overlay_for_report(
            {
                **secondary,
                "events_count": events,
                "candles_count": primary.get("candles_count"),
            }
        )
        script_v = str(variant.get("verdict") or doc.get("verdict_overall") or "kill")
        if diag.get("g0_insufficient"):
            script_v = "blocked"
        final_v, reason = _finalize_phase11_verdict(script_v, overlay)
        pb = variant.get("placebos") or {}
        placebo = (
            f"timestamps aléatoires n={pb.get('random_timestamps', {}).get('n_replicates', 200)} ; "
            f"shift +{pb.get('shift_plus_14d', {}).get('delta_days', 14)}j"
        )
        rows.append(
            Phase11LeaderboardRow(
                signal=signal,
                hypothesis_id=f"P9-ES-PH11-{variant_id}",
                dataset="Statuspage Kraken/Coinbase + BTC OHLC cache 365j",
                events=events,
                bh_rejected=bh_p,
                bh_cells_total=n_cells,
                placebo=placebo,
                cost_verdict=cost_verdict_from_overlay(overlay),
                regime_verdict="non évalué",
                concentration_verdict=overlay.concentration_verdict or "not_assessed",
                red_team_status="en attente (Agent 32)",
                final_verdict=final_v,
                next_action=_phase11_next_action(
                    final_v,
                    signal=signal,
                    hypothesis_id=f"P9-ES-PH11-{variant_id}",
                    rejection_reason=reason,
                ),
                artifact=f"{runs_rel}/exchange_status_deep_dive_365d.json#{variant_id}",
                rejection_reason=reason,
            )
        )
    return rows


def build_phase11_rows() -> list[Phase11LeaderboardRow]:
    runs_dir = PHASE11["runs_dir"]
    runs_rel = str(runs_dir.relative_to(REPO_ROOT)).replace("\\", "/")
    rows: list[Phase11LeaderboardRow] = []
    loaders = [
        (runs_dir / "calendar_micro_baselines.json", _rows_from_calendar),
        (runs_dir / "volume_shock_all_365d.json", _rows_from_volume_shock),
        (runs_dir / "wikipedia_basket_365d.json", _rows_from_wikipedia),
        (runs_dir / "exchange_status_deep_dive_365d.json", _rows_from_exchange_deep_dive),
    ]
    for path, loader in loaders:
        if path.is_file():
            rows.extend(loader(path, runs_rel))
    for sc_path in sorted(runs_dir.glob("p9-sc-001-pr-*.json")):
        rows.extend(_rows_from_stablecoin_file(sc_path, runs_rel))
    return [apply_phase11_red_team_row(r) for r in rows]


def _top_phase11_actions(rows: list[Phase11LeaderboardRow], *, limit: int = 3) -> list[str]:
    priority = {
        "candidate for further OOS testing": 0,
        "retry with fixed data": 1,
        "blocked": 2,
        "weak evidence": 3,
        "not supported": 4,
        "kill": 5,
    }
    seen_signals: set[str] = set()
    oos_rows = [r for r in rows if r.final_verdict == "candidate for further OOS testing"]
    other_rows = sorted(
        [r for r in rows if r.final_verdict != "candidate for further OOS testing"],
        key=lambda r: (priority.get(r.final_verdict, 9), r.hypothesis_id),
    )
    ordered = oos_rows + other_rows
    actions: list[str] = []
    for row in ordered:
        if row.signal in seen_signals:
            continue
        seen_signals.add(row.signal)
        actions.append(f"**{row.hypothesis_id}** (`{row.signal}`) : {row.next_action}")
        if len(actions) >= limit:
            break
    return actions


def render_phase11_md(rows: list[Phase11LeaderboardRow]) -> str:
    runs_rel = str(PHASE11["runs_dir"].relative_to(REPO_ROOT)).replace("\\", "/")
    counts = {v: sum(1 for r in rows if r.final_verdict == v) for v in PHASE11_ALLOWED_VERDICTS}
    oos = counts.get("candidate for further OOS testing", 0)
    lines = [
        "# Alpha research leaderboard (Phase 11)",
        "",
        "**Généré par :** `reports/_build_leaderboard.py --phase11`",
        f"**Périmètre :** JSON sous `{runs_rel}/` (Agents 27–31, calendrier, volume, stables, exchange).",
        "",
        "## Synthèse exécutive",
        "",
        f"- **Hypothèses / variantes évaluées :** {len(rows)}",
        f"- **Candidats OOS retenus (jamais live) :** **{oos}**",
        "- **Signaux tradables / live-ready :** **0** (attendu)",
        f"- **Red team :** intégré depuis `{PHASE11_RED_TEAM_DOC.relative_to(REPO_ROOT).as_posix()}` "
        "(fail/revoked → pas de candidat OOS).",
        "",
        "Verdicts autorisés uniquement : "
        + ", ".join(f"`{v}`" for v in sorted(PHASE11_ALLOWED_VERDICTS))
        + ".",
        "",
        "## Leaderboard",
        "",
        "| Signal | Hypothesis ID | Dataset | Events | BH rejected | Placebo | Cost verdict | Regime verdict | Concentration | Red team | Final verdict | Next action |",
        "|--------|---------------|---------|--------|-------------|---------|--------------|----------------|---------------|----------|---------------|-------------|",
    ]
    for r in rows:
        ds = r.dataset[:45] + ("…" if len(r.dataset) > 45 else "")
        bh = (
            f"{r.bh_rejected}/{r.bh_cells_total}"
            if r.bh_rejected is not None and r.bh_cells_total
            else (str(r.bh_rejected) if r.bh_rejected is not None else "—")
        )
        pla = r.placebo[:50] + ("…" if len(r.placebo) > 50 else "")
        nxt = r.next_action[:48] + ("…" if len(r.next_action) > 48 else "")
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{r.signal}`",
                    f"`{r.hypothesis_id}`",
                    ds,
                    str(r.events) if r.events is not None else "—",
                    bh,
                    pla,
                    r.cost_verdict[:28],
                    r.regime_verdict[:22],
                    r.concentration_verdict[:16],
                    r.red_team_status[:20],
                    f"**{r.final_verdict}**",
                    nxt,
                ]
            )
            + " |"
        )
    lines.extend(["", "## Détail par signal", ""])
    for r in rows:
        lines.append(f"### `{r.signal}` · `{r.hypothesis_id}`")
        lines.append("")
        lines.append(f"- **Artifact :** `{r.artifact}`")
        lines.append(f"- **Events :** {r.events} · **BH :** {r.bh_rejected}/{r.bh_cells_total}")
        lines.append(f"- **Placebos :** {r.placebo}")
        lines.append(f"- **Coûts :** {r.cost_verdict} · **Régime :** {r.regime_verdict}")
        lines.append(f"- **Concentration :** {r.concentration_verdict}")
        lines.append(f"- **Red team :** {r.red_team_status}")
        lines.append(f"- **Verdict final :** **{r.final_verdict}**")
        if r.rejection_reason:
            lines.append(f"- **Caveat :** {r.rejection_reason}")
        lines.append(f"- **Prochaine action :** {r.next_action}")
        lines.append("")
    lines.extend(
        [
            "## Légende des verdicts",
            "",
            "| Verdict | Signification |",
            "|---------|----------------|",
            "| `kill` | Falsification / aucune piste statistique robuste |",
            "| `blocked` | Données ou événements insuffisants pour conclure |",
            "| `not supported` | Test exécuté, BH ne soutient pas l’hypothèse |",
            "| `weak evidence` | Signal fragile, placebos ou coûts non passés |",
            "| `retry with fixed data` | Relancer après correction cache/API |",
            "| `candidate for further OOS testing` | Seule promotion autorisée — hold-out, pas live |",
            "",
            "## Prochaines actions prioritaires (max 3)",
            "",
        ]
    )
    for i, action in enumerate(_top_phase11_actions(rows), start=1):
        lines.append(f"{i}. {action}")
    lines.extend(
        [
            "",
            "## Références",
            "",
            f"- `{PHASE11['run_log']}`",
            "- Comparaison Phase 6 : `reports/PHASE_6_VS_PHASE11.md`",
            "- Rebuild : `python reports/_build_leaderboard.py --phase11`",
            "",
        ]
    )
    return "\n".join(lines)


def render_phase6_vs_phase11_md(
    phase11_rows: list[Phase11LeaderboardRow],
) -> str:
    v2_path = PHASE11["v2_json"]
    v2_by_signal: dict[str, dict[str, Any]] = {}
    if v2_path.is_file():
        v2_doc = json.loads(v2_path.read_text(encoding="utf-8"))
        for row in v2_doc.get("rows") or []:
            v2_by_signal[str(row["signal"])] = row

    def v2_line(signal: str) -> str:
        r = v2_by_signal.get(signal)
        if not r:
            return "— (absent Phase 6)"
        return (
            f"{r.get('nb_events')} evt, BH {r.get('nb_cells_bh_rejected')}, "
            f"verdict `{r.get('verdict')}`"
        )

    wiki_p11 = [r for r in phase11_rows if r.signal.startswith("wikipedia_")]
    cal_p6 = v2_by_signal.get("calendar_weekend_start")
    exch_p6 = v2_by_signal.get("exchange_status_major_incident")
    sc_p6 = v2_by_signal.get("stablecoin_supply_z_high")

    lines = [
        "# Phase 6 vs Phase 11 — comparaison recherche",
        "",
        "**Généré :** 2026-05-19 (Agent 33, archiviste leaderboard Phase 11)",
        "",
        "Comparaison entre `reports/research_runs_v2/` (Phase 6) et le sprint Phase 11 "
        f"(`{str(PHASE11['runs_dir'].relative_to(REPO_ROOT)).replace(chr(92), '/')}`). "
        "Aucune revendication de profitabilité ou de trading live.",
        "",
        "## Delta infrastructure",
        "",
        "| Dimension | Phase 6 | Phase 11 |",
        "|-----------|---------|----------|",
        "| OHLC | Binance public paginé + cache | Cache BTC 365–730j (`use-cache-only`) |",
        "| Wikipedia | Page BTC seule, z par défaut | Panier 8 pages crypto + placebos non-crypto |",
        "| Stablecoins | z≥1.5, 0 evt (bloqué) | Pré-enregistrement P9-SC-001-PR z≥1.0, 4 seuils figés |",
        "| Exchange status | Incident « major », n≈2 | 9 variantes (impact, durée, venue) |",
        "| Calendrier | `weekend_start` 730j | 5 micro-baselines journaliers 730j |",
        "| Volume | — | P9-MS-023 (4 variantes, placebos shift/shuffle) |",
        "| Verdicts | `not supported, move on`, `candidate for OOS retest` | Ensemble fermé Phase 11 (pas de « live-ready ») |",
        "",
        "## Signaux comparables",
        "",
        "### Wikipedia / attention",
        "",
        f"| | Phase 6 (`wikipedia_btc_attention`) | Phase 11 (panier) |",
        f"|---|--------------------------------|-------------------|",
        f"| Phase 6 | {v2_line('wikipedia_btc_attention')} | |",
    ]
    for r in wiki_p11:
        lines.append(
            f"| `{r.signal}` | | {r.events} evt, BH {r.bh_rejected}/{r.bh_cells_total}, "
            f"**{r.final_verdict}** |"
        )
    lines.extend(
        [
            "",
            "Phase 6 : une page, BH 0/5, weak evidence. Phase 11 : panier crypto, BH sur vol/volume "
            "aux seuils z=1,5 et 2,0 ; **révoqués par red team** → weak evidence, **0 OOS retenu**.",
            "",
            "### Stablecoin supply",
            "",
            f"| | Phase 6 | Phase 11 (pré-enregistré z=1.0) |",
            f"|---|---------|-------------------------------|",
            f"| z par défaut | 1.5 → {sc_p6.get('nb_events') if sc_p6 else 0} evt | 1.0, 4 runs JSON |",
        ]
    )
    sc_rows = [r for r in phase11_rows if r.signal.startswith("stablecoin_")]
    for r in sc_rows:
        lines.append(
            f"| `{r.hypothesis_id}` | — | {r.events} evt, BH {r.bh_rejected}, **{r.final_verdict}** |"
        )
    lines.extend(
        [
            "",
            "Phase 11 exerce enfin l’hypothèse sur baisse 7j/30j (36–52 evt) mais les placebos "
            "shift/lag échouent → weak evidence, pas OOS.",
            "",
            "### Exchange incidents",
            "",
            f"- **Phase 6 :** {v2_line('exchange_status_major_incident')}",
            f"- **Phase 11 :** {len([r for r in phase11_rows if r.signal.startswith('exchange_status_')])} variantes ; "
            f"verdict global sprint **kill** (BH primaire vol : 0 rejets robustes).",
            "",
            "### Calendrier",
            "",
            f"- **Phase 6 :** {v2_line('calendar_weekend_start')}",
            "- **Phase 11 :** cinq effets micro (US open, dimanche US, lundi Asie, 3ᵉ vendredi, fin de mois) — "
            "tous **weak evidence** après overlay coûts/turnover ; pas de candidat OOS.",
            "",
            "### Volume shock (nouveau Phase 11)",
            "",
            "Absent en Phase 6. P9-MS-023 : BH sur post_7 mais placebos shift/shuffle à p=1 → **weak evidence** "
            "ou **blocked** (variantes 0 evt).",
            "",
            "## Synthèse",
            "",
            "- **Candidats OOS Phase 11 retenus :** **0** (Wikipedia z≥1,5 / z≥2,0 révoqués par red team).",
            "- **Stablecoins :** débloqués en volume d’événements vs Phase 6, mais falsifiés par placebos → pas d’OOS.",
            "- **Exchange / calendrier / volume :** ne pas promouvoir ; documenter comme contrôles, weak evidence ou kill.",
            "",
            "Rebuild : `python reports/_build_leaderboard.py --phase11`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_phase11() -> int:
    rows = build_phase11_rows()
    out_md: Path = PHASE11["out_md"]
    out_json: Path = PHASE11["out_json"]
    compare_md: Path = PHASE11["compare_md"]
    out_md.write_text(render_phase11_md(rows), encoding="utf-8")
    payload = {
        "generated_by": "reports/_build_leaderboard.py",
        "phase": PHASE11["title"],
        "tradable_count": 0,
        "oos_candidate_count": sum(
            1 for r in rows if r.final_verdict == "candidate for further OOS testing"
        ),
        "allowed_verdicts": sorted(PHASE11_ALLOWED_VERDICTS),
        "cost_assumptions": summarize_cost_assumptions(),
        "rows": [r.to_dict() for r in rows],
        "top_actions": _top_phase11_actions(rows),
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    compare_md.write_text(render_phase6_vs_phase11_md(rows), encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
    print(f"Wrote {compare_md}")
    print(
        f"Rows: {len(rows)}; OOS candidates: {payload['oos_candidate_count']}"
    )
    return len(rows)


def render_md(rows: list[LeaderboardRow], phase: dict[str, Any], smoke_note: str | None) -> str:
    tradable = [r for r in rows if r.verdict in ("tradable", "live-ready", "profitable", "safe")]
    json_count = sum(1 for r in rows if r.artifact)
    blocked_count = sum(1 for r in rows if r.verdict == "blocked")
    economic_reject_count = sum(1 for r in rows if r.economic_reject)
    runs_rel = str(phase["runs_dir"].relative_to(REPO_ROOT)).replace("\\", "/")
    use_economics = phase.get("verdict_rules") == "phase6"
    lines = [
        f"# Alpha research leaderboard ({phase['title']})",
        "",
        "**Generated by:** `reports/_build_leaderboard.py`",
        f"**Scope:** Event-study JSON under `{runs_rel}/` plus blocked runs from `{phase['run_log']}`.",
        "",
        "## Executive summary",
        "",
        f"- **Signals evaluated:** {len(rows)} ({json_count} JSON artifacts + {blocked_count} blocked)",
        f"- **Tradable / live-ready signals:** **{len(tradable)}** (expected: **0**)",
        "- **OOS candidates:** only if verdict is `candidate for OOS retest` — none are deployment-ready.",
        f"- **Blocked runs:** {phase['summary_blocked_note']}",
    ]
    if use_economics:
        lines.append(
            f"- **Economic gate rejections:** **{economic_reject_count}** "
            "(cost, turnover, concentration, or insufficient events — research-only overlay)."
        )
    lines.extend(
        [
            "",
            f"Verdicts follow strict {phase['title']} rules: no signal is marked tradable, profitable, or live-ready.",
            "",
        ]
    )
    if smoke_note:
        lines.extend(["## Runtime smoke", "", smoke_note, ""])
    if use_economics:
        cost_snapshot = summarize_cost_assumptions()
        major_cost = cost_snapshot["example_round_trip_total_pct"]["major_pessimistic"]
        lines.extend(
            [
                "## Tradeability overlay (Phase 7)",
                "",
                "Research-only economic layer on gross event-study returns. "
                "Even when BH-FDR supports a cell, signals fail when costs exceed gross edge, "
                "turnover proxy exceeds 30 %, event count is too low, or concentration is high.",
                "",
                f"- **Default round-trip (major, pessimistic taker/taker):** {_fmt_pct(major_cost)}",
                f"- **Suspect gross threshold:** {_fmt_pct(cost_snapshot['suspect_gross_return_threshold_pct'])}",
                f"- **Turnover proxy:** events / candles (reject if > 30 %)",
                "- **Reference return cell:** BH-rejected `return` on `post_7` when available, else best available.",
                "- **Live-ready:** never — overlay informs rejection only.",
                "",
            ]
        )
    header = (
        "| Signal | Dataset | Period | Events | Cells tested | BH rejected | Best q / p | Placebo | Verdict | Rejection reason | Next action |"
        if not use_economics
        else (
            "| Signal | Dataset | Period | Events | BH rej | Best q/p | Gross avg | RT cost | Net avg | Turnover | Cost dom | Tradeability | Verdict | Econ reject |"
        )
    )
    sep = (
        "|--------|---------|--------|--------|--------------|-------------|------------|---------|---------|------------------|-------------|"
        if not use_economics
        else (
            "|--------|---------|--------|--------|--------|---------|-----------|---------|---------|----------|----------|--------------|---------|-------------|"
        )
    )
    lines.extend(["## Leaderboard", "", header, sep])
    for r in rows:
        if not use_economics:
            reason = (r.rejection_reason or "—").replace("|", "\\|")
            action = r.next_action.replace("|", "\\|")
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{r.signal}`",
                        r.dataset[:60] + ("…" if len(r.dataset) > 60 else ""),
                        r.period,
                        str(r.nb_events) if r.nb_events is not None else "—",
                        str(r.nb_cells_tested) if r.nb_cells_tested is not None else "—",
                        str(r.nb_cells_bh_rejected) if r.nb_cells_bh_rejected is not None else "—",
                        _fmt_p(r.best_corrected_p),
                        r.placebo_status[:40] + ("…" if len(r.placebo_status) > 40 else ""),
                        f"**{r.verdict}**",
                        reason[:50] + ("…" if len(reason) > 50 else ""),
                        action[:55] + ("…" if len(action) > 55 else ""),
                    ]
                )
                + " |"
            )
        else:
            lines.append(
                "| "
                + " | ".join(
                    [
                        f"`{r.signal}`",
                        r.dataset[:40] + ("…" if len(r.dataset) > 40 else ""),
                        r.period,
                        str(r.nb_events) if r.nb_events is not None else "—",
                        str(r.nb_cells_bh_rejected) if r.nb_cells_bh_rejected is not None else "—",
                        _fmt_p(r.best_corrected_p),
                        _fmt_pct(r.gross_avg_return_pct),
                        _fmt_pct(r.round_trip_cost_pct),
                        _fmt_pct(r.net_avg_return_pct),
                        _fmt_turnover(r.turnover_proxy),
                        _fmt_yes_no(r.cost_dominated),
                        (r.tradeability_verdict or "—")[:28],
                        f"**{r.verdict}**",
                        _fmt_yes_no(r.economic_reject),
                    ]
                )
                + " |"
            )
    lines.extend(
        [
            "",
            "## Per-signal detail",
            "",
        ]
    )
    for r in rows:
        lines.append(f"### `{r.signal}`")
        lines.append("")
        if r.artifact:
            lines.append(f"- **Artifact:** `{r.artifact}`")
        if r.script_verdict:
            lines.append(f"- **Script verdict (informational):** `{r.script_verdict}`")
        if r.reference_cell:
            lines.append(f"- **Economic reference cell:** `{r.reference_cell}`")
        if r.gross_avg_return_pct is not None:
            lines.append(
                f"- **Gross / net / RT cost:** {_fmt_pct(r.gross_avg_return_pct)} / "
                f"{_fmt_pct(r.net_avg_return_pct)} / {_fmt_pct(r.round_trip_cost_pct)}"
            )
        if r.turnover_proxy is not None:
            lines.append(f"- **Turnover proxy:** {_fmt_turnover(r.turnover_proxy)}")
        if r.tradeability_verdict:
            lines.append(f"- **Tradeability (research-only):** `{r.tradeability_verdict}`")
        if r.economic_reject_reason:
            lines.append(f"- **Economic rejection:** {r.economic_reject_reason}")
        lines.append(f"- **Leaderboard verdict:** **{r.verdict}**")
        if r.rejection_reason:
            lines.append(f"- **Rejection / caveat:** {r.rejection_reason}")
        lines.append(f"- **Next action:** {r.next_action}")
        lines.append("")
    if use_economics:
        lines.extend(
            [
                "## Tradeability verdict legend",
                "",
                "| Verdict | Meaning |",
                "|---------|---------|",
                "| `economically impossible` | Gross below suspect threshold or deeply unviable |",
                "| `cost dominated` | Gross does not exceed pessimistic round-trip costs |",
                "| `research only` | Net positive but thin edge, or gates G2–G4 incomplete |",
                "| `candidate for paper observation` | Strong net + BH + OOS (never live-ready) |",
                "",
            ]
        )
    lines.extend(
        [
            "## Verdict legend",
            "",
            "| Verdict | Meaning |",
            "|---------|---------|",
            "| `not supported, move on` | BH FDR rejects nothing |",
            "| `weak evidence` | Too few events, demo-only, or BH reject with n<10 |",
            "| `candidate for OOS retest` | BH reject + adequate events + placebo-based p (never live) |",
            "| `blocked` | Missing data, API failure, zero events, or no runnable JSON |",
            "",
            "## References",
            "",
            f"- `{phase['run_log']}` — run log and blocked-run notes",
            f"- Rebuild: `python reports/_build_leaderboard.py{' --v2' if phase['verdict_rules'] == 'phase6' else ''}`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_phase(phase: dict[str, Any], *, smoke_note: str | None) -> int:
    rows = build_rows(phase)
    out_md: Path = phase["out_md"]
    out_json: Path = phase["out_json"]
    out_md.write_text(render_md(rows, phase, smoke_note), encoding="utf-8")
    payload = {
        "generated_by": "reports/_build_leaderboard.py",
        "phase": phase["title"],
        "tradable_count": 0,
        "oos_candidate_count": sum(
            1 for r in rows if r.verdict == "candidate for OOS retest"
        ),
        "economic_reject_count": sum(1 for r in rows if r.economic_reject),
        "cost_assumptions": summarize_cost_assumptions()
        if phase.get("verdict_rules") == "phase6"
        else None,
        "rows": [r.to_dict() for r in rows],
    }
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote {out_md}")
    print(f"Wrote {out_json}")
    print(f"Rows: {len(rows)}; OOS candidates: {payload['oos_candidate_count']}")
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build alpha research leaderboards.")
    parser.add_argument(
        "--v2",
        action="store_true",
        help="Build Phase 6 leaderboard from reports/research_runs_v2/",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Build both Phase 3 and Phase 6 leaderboards.",
    )
    parser.add_argument(
        "--phase11",
        action="store_true",
        help="Build Phase 11 leaderboard from reports/research_runs_phase11/",
    )
    args = parser.parse_args()

    if args.phase11:
        _write_phase11()
        return 0

    smoke_path = REPO_ROOT / "reports" / "runtime_smoke" / "SMOKE_REPORT.md"
    smoke_note = None
    if smoke_path.is_file():
        smoke_note = (
            "Runtime smoke report present at `reports/runtime_smoke/SMOKE_REPORT.md` "
            "(runtime plumbing only; does not upgrade any research verdict)."
        )

    if args.all:
        _write_phase(PHASE3, smoke_note=smoke_note if not args.v2 else None)
        _write_phase(PHASE6, smoke_note=None)
        return 0

    phase = PHASE6 if args.v2 else PHASE3
    _write_phase(phase, smoke_note=smoke_note if phase is PHASE3 else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
