"""Research-only tradeability classification — never live-ready.

Maps gross/net event-study returns and cost assumptions to explicit
verdicts. No path in this module authorizes production or live orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .concentration import classify_concentration_risk
from .cost_model import (
    SUSPECT_GROSS_RETURN_THRESHOLD_PCT,
    LiquidityTier,
    RoundTripCost,
    compute_net_event_return,
    estimate_round_trip_cost,
)

# G2 turnover heuristic — events / candles (see SIGNAL_REJECTION_POLICY.md).
TURNOVER_REJECT_THRESHOLD = 0.30
REFERENCE_RETURN_WINDOWS = ("post_7", "post_3", "post_1")


class TradeabilityVerdict(StrEnum):
    """Ordered from worst to best — still research-only."""

    ECONOMICALLY_IMPOSSIBLE = "economically impossible"
    COST_DOMINATED = "cost dominated"
    RESEARCH_ONLY = "research only"
    CANDIDATE_FOR_PAPER_OBSERVATION = "candidate for paper observation"

    @property
    def is_live_ready(self) -> bool:
        """Always ``False`` — live promotion is out of scope."""
        return False


@dataclass(frozen=True)
class TradeabilityAssessment:
    """Full classification output for logging and reports."""

    verdict: TradeabilityVerdict
    gross_mean_return_pct: float
    net_mean_return_pct: float
    round_trip_cost_pct: float
    reject: bool
    reason: str
    live_ready: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "gross_mean_return_pct": self.gross_mean_return_pct,
            "net_mean_return_pct": self.net_mean_return_pct,
            "round_trip_cost_pct": self.round_trip_cost_pct,
            "reject": self.reject,
            "reason": self.reason,
            "live_ready": self.live_ready,
        }


def classify_tradeability(
    gross_mean_return_pct: float,
    *,
    liquidity_tier: LiquidityTier = "major",
    round_trip_cost: RoundTripCost | None = None,
    n_events: int | None = None,
    min_events: int = 5,
    bh_supported: bool = False,
    oos_confirmed: bool = False,
) -> TradeabilityAssessment:
    """Classify whether a signal survives conservative economic realism.

    Verdict ladder (best case still **not** live-ready):

    1. ``economically impossible`` — gross below suspect threshold, or
       net deeply negative vs costs.
    2. ``cost dominated`` — gross positive but net ≤ 0 after costs.
    3. ``research only`` — net positive but thin, or gates G2/G4 not met.
    4. ``candidate for paper observation`` — net clears costs with margin,
       sufficient events, and optional BH/OOS flags (paper **observation**
       only, never production).

    Parameters
    ----------
    gross_mean_return_pct:
        Mean gross return per event (fraction, e.g. ``0.012`` = 1.2 %).
    liquidity_tier:
        Drives default spread/slippage band in ``estimate_round_trip_cost``.
    round_trip_cost:
        Pre-computed cost; default is pessimistic taker/taker + high spread.
    n_events:
        Event count; if below ``min_events``, caps verdict at research-only.
    min_events:
        Power floor aligned with G0 (default 5).
    bh_supported:
        Event study survived BH-FDR at α = 0.05 (G1).
    oos_confirmed:
        Out-of-sample reproduction documented (G4).
    """
    cost = round_trip_cost or estimate_round_trip_cost(
        liquidity_tier=liquidity_tier,
        pessimistic=True,
    )
    net = compute_net_event_return(gross_mean_return_pct, cost)
    cost_total = cost.total_pct

    if gross_mean_return_pct < SUSPECT_GROSS_RETURN_THRESHOLD_PCT:
        return TradeabilityAssessment(
            verdict=TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE,
            gross_mean_return_pct=gross_mean_return_pct,
            net_mean_return_pct=net,
            round_trip_cost_pct=cost_total,
            reject=True,
            reason=(
                f"gross mean {gross_mean_return_pct:.4%} below suspect threshold "
                f"{SUSPECT_GROSS_RETURN_THRESHOLD_PCT:.4%} per trade"
            ),
        )

    if net <= 0.0:
        if gross_mean_return_pct <= cost_total:
            reason = (
                f"gross {gross_mean_return_pct:.4%} does not exceed round-trip cost "
                f"{cost_total:.4%}"
            )
        else:
            reason = f"net expectancy {net:.4%} ≤ 0 after costs"
        return TradeabilityAssessment(
            verdict=TradeabilityVerdict.COST_DOMINATED,
            gross_mean_return_pct=gross_mean_return_pct,
            net_mean_return_pct=net,
            round_trip_cost_pct=cost_total,
            reject=True,
            reason=reason,
        )

    thin_edge_buffer = cost_total * 0.5
    if net < thin_edge_buffer:
        return TradeabilityAssessment(
            verdict=TradeabilityVerdict.RESEARCH_ONLY,
            gross_mean_return_pct=gross_mean_return_pct,
            net_mean_return_pct=net,
            round_trip_cost_pct=cost_total,
            reject=False,
            reason=(
                f"net {net:.4%} positive but below half cost buffer "
                f"({thin_edge_buffer:.4%}); edge too thin for promotion"
            ),
        )

    if n_events is not None and n_events < min_events:
        return TradeabilityAssessment(
            verdict=TradeabilityVerdict.RESEARCH_ONLY,
            gross_mean_return_pct=gross_mean_return_pct,
            net_mean_return_pct=net,
            round_trip_cost_pct=cost_total,
            reject=False,
            reason=f"only {n_events} events (< {min_events}); insufficient power",
        )

    if bh_supported and oos_confirmed and net >= cost_total:
        return TradeabilityAssessment(
            verdict=TradeabilityVerdict.CANDIDATE_FOR_PAPER_OBSERVATION,
            gross_mean_return_pct=gross_mean_return_pct,
            net_mean_return_pct=net,
            round_trip_cost_pct=cost_total,
            reject=False,
            reason=(
                "net positive after pessimistic costs; BH and OOS documented — "
                "paper observation only, not live-ready"
            ),
        )

    if bh_supported and net >= cost_total:
        return TradeabilityAssessment(
            verdict=TradeabilityVerdict.RESEARCH_ONLY,
            gross_mean_return_pct=gross_mean_return_pct,
            net_mean_return_pct=net,
            round_trip_cost_pct=cost_total,
            reject=False,
            reason="BH supported but OOS not confirmed; remain in research",
        )

    return TradeabilityAssessment(
        verdict=TradeabilityVerdict.RESEARCH_ONLY,
        gross_mean_return_pct=gross_mean_return_pct,
        net_mean_return_pct=net,
        round_trip_cost_pct=cost_total,
        reject=False,
        reason="net positive after costs; complete G2–G4 before paper candidacy",
    )


@dataclass(frozen=True)
class LeaderboardEconomicOverlay:
    """Economic layer for alpha research leaderboard V2 (research-only)."""

    gross_avg_return_pct: float | None
    round_trip_cost_pct: float | None
    net_avg_return_pct: float | None
    turnover_proxy: float | None
    cost_dominated: bool
    tradeability_verdict: str | None
    economic_reject: bool
    economic_reject_reason: str | None
    reference_cell: str | None
    concentration_verdict: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "gross_avg_return_pct": self.gross_avg_return_pct,
            "round_trip_cost_pct": self.round_trip_cost_pct,
            "net_avg_return_pct": self.net_avg_return_pct,
            "turnover_proxy": self.turnover_proxy,
            "cost_dominated": self.cost_dominated,
            "tradeability_verdict": self.tradeability_verdict,
            "economic_reject": self.economic_reject,
            "economic_reject_reason": self.economic_reject_reason,
            "reference_cell": self.reference_cell,
            "concentration_verdict": self.concentration_verdict,
        }


def select_return_cell_for_economics(
    cells: list[dict[str, Any]],
    *,
    bh_rejected_mask: list[bool] | None = None,
) -> dict[str, Any] | None:
    """Pick the return cell used for gross/net economics on the leaderboard.

    Preference order: BH-rejected ``return`` cells on ``post_7`` → ``post_3``
    → ``post_1``; then the same windows among all return cells; finally any
    return cell.
    """
    if not cells:
        return None

    return_cells = [c for c in cells if c.get("metric") == "return"]
    if not return_cells:
        return None

    bh_return_cells: list[dict[str, Any]] = []
    if bh_rejected_mask is not None and len(bh_rejected_mask) == len(cells):
        bh_return_cells = [
            c
            for c, rejected in zip(cells, bh_rejected_mask, strict=True)
            if rejected and c.get("metric") == "return"
        ]

    for pool in (bh_return_cells, return_cells):
        if not pool:
            continue
        for window in REFERENCE_RETURN_WINDOWS:
            for cell in pool:
                if cell.get("window") == window:
                    return cell
        return pool[0]
    return None


def compute_turnover_proxy(
    n_events: int,
    candles_count: int | None,
    *,
    threshold: float = TURNOVER_REJECT_THRESHOLD,
) -> tuple[float | None, bool]:
    """Return ``(events/candles, turnover_too_high)`` per G2 heuristic."""
    if candles_count is None or candles_count <= 0:
        return None, False
    if n_events < 0:
        raise ValueError(f"n_events must be non-negative, got {n_events!r}")
    ratio = n_events / candles_count
    return ratio, ratio > threshold


def _reference_cell_label(cell: dict[str, Any]) -> str:
    return f"{cell.get('metric', '?')}/{cell.get('window', '?')}"


def build_leaderboard_economic_overlay(
    report: dict[str, Any],
    *,
    liquidity_tier: LiquidityTier = "major",
    min_events: int = 5,
    turnover_threshold: float = TURNOVER_REJECT_THRESHOLD,
    bh_supported: bool = False,
    oos_confirmed: bool = False,
) -> LeaderboardEconomicOverlay:
    """Compute deterministic economic overlay fields from an event-study JSON.

    Applies G2–G3 gates: turnover, event count, concentration (when per-event
    contributions exist), and pessimistic round-trip costs. Even when BH-FDR
    supports a cell, ``economic_reject`` is True when any gate fails.
    """
    cells = report.get("cells") or []
    bh_mask = report.get("bh_rejected_mask")
    n_events = int(report.get("events_count") or report.get("events_used") or 0)
    candles_count = report.get("candles_count")
    candles_int = int(candles_count) if candles_count is not None else None

    turnover_proxy, turnover_high = compute_turnover_proxy(
        n_events,
        candles_int,
        threshold=turnover_threshold,
    )

    reference = select_return_cell_for_economics(
        cells,
        bh_rejected_mask=bh_mask if isinstance(bh_mask, list) else None,
    )

    contributions = report.get("event_returns") or report.get("contributions")
    concentration_verdict: str | None = "not_assessed"
    if isinstance(contributions, list) and contributions:
        event_months = report.get("event_months")
        event_timestamps = report.get("event_timestamps")
        conc = classify_concentration_risk(
            contributions,
            event_months=event_months if isinstance(event_months, list) else None,
            event_timestamps=event_timestamps if isinstance(event_timestamps, list) else None,
            min_events=min_events,
        )
        concentration_verdict = conc.verdict

    reject_reasons: list[str] = []

    if n_events < min_events:
        reject_reasons.append(
            f"only {n_events} events (< {min_events}); insufficient power"
        )

    if turnover_high and turnover_proxy is not None:
        reject_reasons.append(
            f"turnover proxy {turnover_proxy:.1%} > {turnover_threshold:.0%} "
            "(signal too noisy for distinct events)"
        )

    if concentration_verdict == "high_concentration_risk":
        reject_reasons.append("aggregate dominated by few events or one month (G2)")
    elif concentration_verdict == "insufficient_evidence":
        reject_reasons.append("concentration check: insufficient events for robustness")

    if reference is None:
        if not reject_reasons:
            return LeaderboardEconomicOverlay(
                gross_avg_return_pct=None,
                round_trip_cost_pct=None,
                net_avg_return_pct=None,
                turnover_proxy=turnover_proxy,
                cost_dominated=False,
                tradeability_verdict=None,
                economic_reject=bool(reject_reasons),
                economic_reject_reason="; ".join(reject_reasons) if reject_reasons else None,
                reference_cell=None,
                concentration_verdict=concentration_verdict,
            )
        return LeaderboardEconomicOverlay(
            gross_avg_return_pct=None,
            round_trip_cost_pct=None,
            net_avg_return_pct=None,
            turnover_proxy=turnover_proxy,
            cost_dominated=False,
            tradeability_verdict=None,
            economic_reject=True,
            economic_reject_reason="; ".join(reject_reasons),
            reference_cell=None,
            concentration_verdict=concentration_verdict,
        )

    gross = float(reference["mean"])
    cost = estimate_round_trip_cost(liquidity_tier=liquidity_tier, pessimistic=True)
    net = compute_net_event_return(gross, cost)
    assessment = classify_tradeability(
        gross,
        liquidity_tier=liquidity_tier,
        round_trip_cost=cost,
        n_events=n_events,
        min_events=min_events,
        bh_supported=bh_supported,
        oos_confirmed=oos_confirmed,
    )

    cost_dominated = assessment.verdict in (
        TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE,
        TradeabilityVerdict.COST_DOMINATED,
    )

    if assessment.reject:
        reject_reasons.append(assessment.reason)

    economic_reject = bool(reject_reasons)
    return LeaderboardEconomicOverlay(
        gross_avg_return_pct=gross,
        round_trip_cost_pct=cost.total_pct,
        net_avg_return_pct=net,
        turnover_proxy=turnover_proxy,
        cost_dominated=cost_dominated,
        tradeability_verdict=assessment.verdict.value,
        economic_reject=economic_reject,
        economic_reject_reason="; ".join(reject_reasons) if reject_reasons else None,
        reference_cell=_reference_cell_label(reference),
        concentration_verdict=concentration_verdict,
    )


def apply_economic_verdict_overlay(
    verdict: str,
    rejection_reason: str | None,
    overlay: LeaderboardEconomicOverlay,
) -> tuple[str, str | None]:
    """Downgrade statistical verdict when economic gates fail (research-only).

    Even ``candidate for OOS retest`` is capped to ``weak evidence`` when
    ``overlay.economic_reject`` is True.
    """
    if not overlay.economic_reject:
        return verdict, rejection_reason

    econ_reason = overlay.economic_reject_reason or "economic gates failed"
    if verdict in ("candidate for OOS retest", "supported"):
        merged = econ_reason if rejection_reason is None else f"{rejection_reason}; {econ_reason}"
        return "weak evidence", merged

    if verdict == "weak evidence" and rejection_reason is None:
        return verdict, econ_reason

    if rejection_reason is None:
        return verdict, econ_reason

    if econ_reason not in rejection_reason:
        return verdict, f"{rejection_reason}; {econ_reason}"
    return verdict, rejection_reason


def reject_if_cost_dominated(
    gross_mean_return_pct: float,
    *,
    liquidity_tier: LiquidityTier = "major",
    round_trip_cost: RoundTripCost | None = None,
    n_events: int | None = None,
) -> tuple[bool, str, TradeabilityVerdict]:
    """Return ``(reject, reason, verdict)`` for G3-style automatic rejection.

    Rejects when:

    - gross mean is below the suspect threshold (0.5 %), or
    - net expectancy ≤ 0 after pessimistic round-trip costs, or
    - verdict is ``economically impossible`` or ``cost dominated``.
    """
    assessment = classify_tradeability(
        gross_mean_return_pct,
        liquidity_tier=liquidity_tier,
        round_trip_cost=round_trip_cost,
        n_events=n_events,
    )
    reject = assessment.reject or assessment.verdict in (
        TradeabilityVerdict.ECONOMICALLY_IMPOSSIBLE,
        TradeabilityVerdict.COST_DOMINATED,
    )
    return reject, assessment.reason, assessment.verdict
