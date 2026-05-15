"""Pydantic schemas for the agent's internal data flow.

These structures are the *only* contract between modules. The JSON forms
produced by `.model_dump_json()` are also what we persist to JSONL files and
return from the dashboard JSON endpoints, so they must stay backwards
compatible.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .utils import new_id, utc_now_iso


Action = Literal["BUY", "SELL", "HOLD"]
Mode = Literal["dry_run", "paper", "live"]
Regime = Literal[
    "TRENDING_UP",
    "TRENDING_DOWN",
    "RANGING",
    "HIGH_VOLATILITY",
    "LOW_LIQUIDITY",
    "UNKNOWN",
]


class Features(BaseModel):
    model_config = ConfigDict(extra="ignore")

    symbol: str
    last_price: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread_bps: float = 0.0
    return_5m: float = 0.0
    return_15m: float = 0.0
    return_1h: float = 0.0
    volatility_15m: float = 0.0
    volatility_1h: float = 0.0
    high_1h: float = 0.0
    low_1h: float = 0.0
    distance_from_high_1h: float = 0.0
    distance_from_low_1h: float = 0.0
    volume_1h: float = 0.0
    source: str = "kraken_cli"
    as_of: str = Field(default_factory=utc_now_iso)


class StrategyVote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    score: float = 0.0
    confidence: float = 0.0
    rationale: str = ""


class EnsembleResult(BaseModel):
    final_score: float
    action: Action
    confidence: float
    suggested_size_usd: float
    votes: list[StrategyVote]
    regime: Regime
    rationale: str = ""


class RiskCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class RiskResult(BaseModel):
    approved: bool
    reasons: list[str] = Field(default_factory=list)
    checks: list[RiskCheck] = Field(default_factory=list)
    adjusted_size_usd: float = 0.0
    blocked_for_live_flags: bool = False


class ExecutionResult(BaseModel):
    status: Literal[
        "dry_run_logged",
        "paper_filled",
        "paper_failed",
        "live_validated",
        "live_filled",
        "live_failed",
        "blocked",
        "blocked_paper_not_initialized",
        "skipped",
    ]
    mode: Mode
    order_id: Optional[str] = None
    symbol: Optional[str] = None
    action: Action = "HOLD"
    requested_size_usd: float = 0.0
    filled_size_usd: float = 0.0
    fill_price: Optional[float] = None
    volume: Optional[float] = None
    fee: Optional[float] = None
    error: Optional[str] = None
    raw: dict[str, Any] = Field(default_factory=dict)
    at: str = Field(default_factory=utc_now_iso)


class Position(BaseModel):
    symbol: str
    quantity: float
    avg_entry_price: float
    market_price: float
    notional_usd: float
    unrealized_pnl_usd: float = 0.0
    realized_pnl_usd: float = 0.0


class PortfolioSnapshot(BaseModel):
    base_currency: str = "USD"
    cash_usd: float = 0.0
    positions: list[Position] = Field(default_factory=list)
    equity_usd: float = 0.0
    source: str = "local_estimate"
    as_of: str = Field(default_factory=utc_now_iso)


class PnLSnapshot(BaseModel):
    realized_usd: float = 0.0
    unrealized_usd: float = 0.0
    net_usd: float = 0.0
    equity_usd: float = 0.0
    drawdown_pct: float = 0.0
    source: str = "local_estimate"
    note: str = ""
    as_of: str = Field(default_factory=utc_now_iso)


class LLMExplanation(BaseModel):
    summary: str = ""
    why_this_trade: str = ""
    risk_notes: str = ""
    confidence_comment: str = ""


class Actionability(BaseModel):
    """Why the agent considers (or refuses) a symbol actionable this cycle.

    The actionability layer runs *between* the ensemble and the risk manager:
    it can downgrade a BUY/SELL to HOLD before risk evaluation when calibration
    rules forbid the action (below threshold, negative opportunity, SELL
    without an open position, etc.). The risk manager then sees a clean
    ensemble and only re-evaluates trades that already passed actionability.
    """

    model_config = ConfigDict(extra="ignore")

    buy_eligible: bool = False
    sell_eligible: bool = False
    reason: str = ""
    size_dampened: bool = False
    size_factor: float = 1.0
    opportunity_score: float = 0.0
    liquidity_score: float = 0.0


class Decision(BaseModel):
    """Canonical decision record persisted to JSONL + SQLite."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(default_factory=lambda: new_id("dec"))
    cycle_id: Optional[str] = None
    symbol: str
    action: Action
    final_score: float
    confidence: float
    suggested_size_usd: float
    approved_size_usd: float = 0.0
    regime: Regime = "UNKNOWN"
    features: Features
    votes: list[StrategyVote] = Field(default_factory=list)
    risk: RiskResult
    execution: ExecutionResult
    actionability: Optional[Actionability] = None
    llm: Optional[LLMExplanation] = None
    mode: Mode = "dry_run"
    rationale: str = ""
    at: str = Field(default_factory=utc_now_iso)


__all__ = [
    "Action",
    "Mode",
    "Regime",
    "Features",
    "StrategyVote",
    "EnsembleResult",
    "RiskCheck",
    "RiskResult",
    "ExecutionResult",
    "Position",
    "PortfolioSnapshot",
    "PnLSnapshot",
    "LLMExplanation",
    "Actionability",
    "Decision",
]
