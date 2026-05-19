"""Conservative Kraken spot cost assumptions for research-only gates.

This module answers one question: *after pessimistic fees and
slippage, does a gross event-study return still leave room for
expectancy?* It never imports execution, risk, or backtest code.

Hard contract
-------------
- **Stdlib only** — no pandas / numpy.
- **Pure functions** — deterministic, no network I/O.
- **Research-only** — outputs inform ``classify_tradeability`` and
  manual G3 checks; they do **not** authorize live trading.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

# ---------------------------------------------------------------------------
# Published defaults (Kraken spot, small account, conservative)
# ---------------------------------------------------------------------------

MAKER_FEE_PCT: float = 0.0025  # 0.25 % per leg
TAKER_FEE_PCT: float = 0.0040  # 0.40 % per leg
ROUND_TRIP_TAKER_TAKER_PCT: float = 0.0080  # 0.80 % buy + sell taker

SPREAD_SLIPPAGE_MAJORS_LOW_PCT: float = 0.0005  # 0.05 %
SPREAD_SLIPPAGE_MAJORS_HIGH_PCT: float = 0.0020  # 0.20 %
SPREAD_SLIPPAGE_ALTS_LOW_PCT: float = 0.0020  # 0.20 %
SPREAD_SLIPPAGE_ALTS_HIGH_PCT: float = 0.0060  # 0.60 %

# Gross mean below this per trade is treated as suspect (noise / data bug).
SUSPECT_GROSS_RETURN_THRESHOLD_PCT: float = 0.005  # 0.50 %

LiquidityTier = Literal["major", "alt"]
ExecutionStyle = Literal[
    "maker_maker",
    "taker_taker",
    "maker_taker",
    "taker_maker",
]


@dataclass(frozen=True)
class RoundTripCost:
    """Decomposed round-trip cost in return space (fraction, not bps)."""

    fee_entry_pct: float
    fee_exit_pct: float
    spread_slippage_pct: float
    total_pct: float
    liquidity_tier: LiquidityTier
    execution_style: ExecutionStyle
    pessimistic: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "fee_entry_pct": self.fee_entry_pct,
            "fee_exit_pct": self.fee_exit_pct,
            "spread_slippage_pct": self.spread_slippage_pct,
            "total_pct": self.total_pct,
            "liquidity_tier": self.liquidity_tier,
            "execution_style": self.execution_style,
            "pessimistic": self.pessimistic,
        }


def _fee_for_leg(side: Literal["maker", "taker"]) -> float:
    return MAKER_FEE_PCT if side == "maker" else TAKER_FEE_PCT


def _execution_legs(style: ExecutionStyle) -> tuple[Literal["maker", "taker"], Literal["maker", "taker"]]:
    mapping: dict[ExecutionStyle, tuple[Literal["maker", "taker"], Literal["maker", "taker"]]] = {
        "maker_maker": ("maker", "maker"),
        "taker_taker": ("taker", "taker"),
        "maker_taker": ("maker", "taker"),
        "taker_maker": ("taker", "maker"),
    }
    return mapping[style]


def _spread_slippage_for_tier(
    liquidity_tier: LiquidityTier,
    *,
    pessimistic: bool,
) -> float:
    if liquidity_tier == "major":
        return (
            SPREAD_SLIPPAGE_MAJORS_HIGH_PCT
            if pessimistic
            else SPREAD_SLIPPAGE_MAJORS_LOW_PCT
        )
    return (
        SPREAD_SLIPPAGE_ALTS_HIGH_PCT
        if pessimistic
        else SPREAD_SLIPPAGE_ALTS_LOW_PCT
    )


def estimate_round_trip_cost(
    *,
    liquidity_tier: LiquidityTier = "major",
    execution_style: ExecutionStyle = "taker_taker",
    pessimistic: bool = True,
    spread_slippage_pct: float | None = None,
) -> RoundTripCost:
    """Estimate total round-trip cost as a fraction of notional.

    Parameters
    ----------
    liquidity_tier:
        ``major`` (BTC/ETH and similarly deep pairs) or ``alt``.
    execution_style:
        Fee schedule for entry and exit legs. Default ``taker_taker``
        matches the G3 bar in ``docs/SIGNAL_REJECTION_POLICY.md``.
    pessimistic:
        When ``True`` (default), use the **high** end of the documented
        spread/slippage band for the tier.
    spread_slippage_pct:
        Optional override for the spread/slippage component (fraction).
    """
    entry_leg, exit_leg = _execution_legs(execution_style)
    fee_entry = _fee_for_leg(entry_leg)
    fee_exit = _fee_for_leg(exit_leg)
    slip = (
        spread_slippage_pct
        if spread_slippage_pct is not None
        else _spread_slippage_for_tier(liquidity_tier, pessimistic=pessimistic)
    )
    total = fee_entry + fee_exit + slip
    return RoundTripCost(
        fee_entry_pct=fee_entry,
        fee_exit_pct=fee_exit,
        spread_slippage_pct=slip,
        total_pct=total,
        liquidity_tier=liquidity_tier,
        execution_style=execution_style,
        pessimistic=pessimistic,
    )


def compute_net_event_return(
    gross_return_pct: float,
    round_trip_cost: RoundTripCost | float,
) -> float:
    """Subtract round-trip cost from a gross event return (both fractions)."""
    cost = round_trip_cost.total_pct if isinstance(round_trip_cost, RoundTripCost) else float(
        round_trip_cost
    )
    return gross_return_pct - cost


def summarize_cost_assumptions() -> Mapping[str, Any]:
    """Return a JSON-serializable snapshot of default cost assumptions."""
    major_pess = estimate_round_trip_cost(liquidity_tier="major", pessimistic=True)
    major_opt = estimate_round_trip_cost(liquidity_tier="major", pessimistic=False)
    alt_pess = estimate_round_trip_cost(liquidity_tier="alt", pessimistic=True)
    alt_opt = estimate_round_trip_cost(liquidity_tier="alt", pessimistic=False)
    return {
        "venue": "kraken_spot_small_account",
        "research_only": True,
        "never_live_ready": True,
        "fees": {
            "maker_pct": MAKER_FEE_PCT,
            "taker_pct": TAKER_FEE_PCT,
            "round_trip_taker_taker_pct": ROUND_TRIP_TAKER_TAKER_PCT,
        },
        "spread_slippage_bands_pct": {
            "majors": [SPREAD_SLIPPAGE_MAJORS_LOW_PCT, SPREAD_SLIPPAGE_MAJORS_HIGH_PCT],
            "alts": [SPREAD_SLIPPAGE_ALTS_LOW_PCT, SPREAD_SLIPPAGE_ALTS_HIGH_PCT],
        },
        "suspect_gross_return_threshold_pct": SUSPECT_GROSS_RETURN_THRESHOLD_PCT,
        "default_execution_style": "taker_taker",
        "example_round_trip_total_pct": {
            "major_pessimistic": major_pess.total_pct,
            "major_optimistic_spread": major_opt.total_pct,
            "alt_pessimistic": alt_pess.total_pct,
            "alt_optimistic_spread": alt_opt.total_pct,
        },
    }
