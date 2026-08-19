"""Pure paper-observation arithmetic for Phase 10 research.

This module simulates *fictive* round-trip trades with conservative
fees/spread/slippage and evaluates eligibility / weekly verdicts.
It never imports live-trading code and performs no network I/O.

See ``docs/PAPER_OBSERVATION_DESIGN.md`` for the full design.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

WeeklyVerdictLabel = Literal[
    "observe",
    "degrade",
    "reject",
    "insufficient_activity",
]


@dataclass(frozen=True)
class PaperCostModel:
    """Conservative cost assumptions aligned with SIGNAL_REJECTION_POLICY."""

    maker_bps: float = 25.0
    taker_bps: float = 40.0
    spread_bps: float = 10.0
    slippage_bps: float = 5.0

    def per_leg_cost_fraction(self, *, use_taker: bool = True) -> float:
        fee_bps = self.taker_bps if use_taker else self.maker_bps
        total_bps = fee_bps + (self.spread_bps / 2.0) + self.slippage_bps
        return total_bps / 10_000.0

    def round_trip_cost_fraction(self, *, use_taker: bool = True) -> float:
        return 2.0 * self.per_leg_cost_fraction(use_taker=use_taker)

    def round_trip_fees_only_fraction(self, *, use_taker: bool = True) -> float:
        """G3 bar: taker 40+40 bps = 0.80 % without spread/slippage."""
        fee_bps = self.taker_bps if use_taker else self.maker_bps
        return 2.0 * fee_bps / 10_000.0


DEFAULT_COST_MODEL = PaperCostModel()


@dataclass(frozen=True)
class EligibilityInput:
    """Snapshot of research gates needed to start paper observation."""

    n_events: int
    bh_rejected: int
    placebo_p_value: float
    mean_return_post_7: float
    jackknife_sign_preserved: bool
    jackknife_mean_drop_fraction: float
    hit_rate_post_7: float
    events_to_candles_ratio: float
    oos_survives: bool
    max_event_pnl_share: float
    n_regime_terciles_same_sign: int
    signal_id: str = ""
    min_events: int = 5
    exchange_status_min_events: int = 10


@dataclass(frozen=True)
class EligibilityReport:
    eligible: bool
    reason_codes: tuple[str, ...]


def check_paper_eligibility(
    inp: EligibilityInput,
    *,
    cost_model: PaperCostModel = DEFAULT_COST_MODEL,
) -> EligibilityReport:
    """Return eligibility and explicit failure reason codes (G0–G4c)."""
    codes: list[str] = []
    min_ev = (
        inp.exchange_status_min_events
        if inp.signal_id.startswith("exchange_status")
        else inp.min_events
    )

    if inp.n_events < min_ev:
        codes.append("ELIG_G0_FAIL_EVENTS")
    if inp.bh_rejected < 1:
        codes.append("ELIG_G1_FAIL_BH")
    if inp.placebo_p_value >= 0.05:
        codes.append("ELIG_G1_FAIL_PLACEBO")
    if not inp.jackknife_sign_preserved:
        codes.append("ELIG_G2_FAIL_ROBUSTNESS")
    if inp.jackknife_mean_drop_fraction > 0.50:
        codes.append("ELIG_G2_FAIL_ROBUSTNESS")
    if inp.hit_rate_post_7 < 0.50:
        codes.append("ELIG_G2_FAIL_ROBUSTNESS")
    if inp.events_to_candles_ratio > 0.30:
        codes.append("ELIG_G2_FAIL_TURNOVER")

    g3_bar = cost_model.round_trip_fees_only_fraction(use_taker=True)
    if inp.mean_return_post_7 - g3_bar < 0:
        codes.append("ELIG_G3_FAIL_COST_DOMINANT")

    if not inp.oos_survives:
        codes.append("ELIG_G4_FAIL_OOS")
    if inp.max_event_pnl_share > 0.50:
        codes.append("ELIG_FAIL_CONCENTRATION")
    if inp.n_regime_terciles_same_sign < 2:
        codes.append("ELIG_FAIL_REGIME")

    if not codes:
        return EligibilityReport(eligible=True, reason_codes=("ELIG_PASS_ALL",))
    return EligibilityReport(eligible=False, reason_codes=tuple(codes))


@dataclass(frozen=True)
class PaperTradeResult:
    gross_return: float
    net_return: float
    cost_drag: float
    reason_codes: tuple[str, ...]


def simulate_round_trip(
    gross_return: float,
    *,
    cost_model: PaperCostModel = DEFAULT_COST_MODEL,
    use_taker: bool = True,
    expected_edge_bps: float | None = None,
) -> PaperTradeResult:
    """Apply round-trip costs to a gross return fraction."""
    cost = cost_model.round_trip_cost_fraction(use_taker=use_taker)
    codes: list[str] = []

    if expected_edge_bps is not None:
        cost_bps = cost * 10_000.0
        if expected_edge_bps < cost_bps:
            codes.append("SKIP_EDGE_BELOW_COSTS")

    codes.append("COST_TAKER_ROUND_TRIP" if use_taker else "COST_MAKER_ROUND_TRIP")
    net = gross_return - cost
    return PaperTradeResult(
        gross_return=gross_return,
        net_return=net,
        cost_drag=cost,
        reason_codes=tuple(codes),
    )


@dataclass(frozen=True)
class WeeklyVerdict:
    verdict: WeeklyVerdictLabel
    reason_codes: tuple[str, ...]
    net_pnl_fraction: float
    cost_drag_ratio: float
    max_trade_concentration: float
    n_closed: int


def compute_weekly_verdict(
    closed_trades: Sequence[PaperTradeResult],
    *,
    min_trades: int = 2,
    concentration_limit: float = 0.50,
    cost_dominance_limit: float = 0.80,
) -> WeeklyVerdict:
    """Aggregate closed fictive trades into a weekly observation verdict."""
    n = len(closed_trades)
    if n < min_trades:
        return WeeklyVerdict(
            verdict="insufficient_activity",
            reason_codes=("WEEKLY_INSUFFICIENT_ACTIVITY",),
            net_pnl_fraction=0.0,
            cost_drag_ratio=0.0,
            max_trade_concentration=0.0,
            n_closed=n,
        )

    net_pnl = sum(t.net_return for t in closed_trades)
    gross_sum = sum(t.gross_return for t in closed_trades)
    cost_sum = sum(t.cost_drag for t in closed_trades)
    eps = 1e-12
    cost_drag_ratio = cost_sum / max(abs(gross_sum), eps)

    if abs(net_pnl) < eps:
        max_conc = 0.0
    else:
        max_conc = max(abs(t.net_return) for t in closed_trades) / abs(net_pnl)

    codes: list[str] = []

    if n == 1 and closed_trades[0].net_return < -2.0 * closed_trades[0].cost_drag:
        codes.append("WEEKLY_REJECT")
        return WeeklyVerdict(
            verdict="reject",
            reason_codes=tuple(codes),
            net_pnl_fraction=net_pnl,
            cost_drag_ratio=cost_drag_ratio,
            max_trade_concentration=max_conc,
            n_closed=n,
        )

    if net_pnl < -0.5 * cost_sum or max_conc > concentration_limit:
        codes.append("WEEKLY_REJECT")
        return WeeklyVerdict(
            verdict="reject",
            reason_codes=tuple(codes),
            net_pnl_fraction=net_pnl,
            cost_drag_ratio=cost_drag_ratio,
            max_trade_concentration=max_conc,
            n_closed=n,
        )

    if net_pnl <= 0:
        codes.append("WEEKLY_DEGRADE")
        return WeeklyVerdict(
            verdict="degrade",
            reason_codes=tuple(codes),
            net_pnl_fraction=net_pnl,
            cost_drag_ratio=cost_drag_ratio,
            max_trade_concentration=max_conc,
            n_closed=n,
        )

    if cost_drag_ratio >= cost_dominance_limit:
        codes.append("WEEKLY_DEGRADE")
        return WeeklyVerdict(
            verdict="degrade",
            reason_codes=tuple(codes),
            net_pnl_fraction=net_pnl,
            cost_drag_ratio=cost_drag_ratio,
            max_trade_concentration=max_conc,
            n_closed=n,
        )

    codes.append("WEEKLY_OBSERVE")
    return WeeklyVerdict(
        verdict="observe",
        reason_codes=tuple(codes),
        net_pnl_fraction=net_pnl,
        cost_drag_ratio=cost_drag_ratio,
        max_trade_concentration=max_conc,
        n_closed=n,
    )
