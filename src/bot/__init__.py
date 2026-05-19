"""Paper trading bot MVP (Phase 14) — stdlib-first, no live execution."""

from .metrics import Verdict, compute_metrics, compute_verdict
from .orders import Fill, Order
from .paper_engine import BacktestResult, BotCandle, run_paper_backtest
from .portfolio import PaperPortfolio
from .risk_manager import RiskConfig, RiskDecision, RiskManager

__all__ = [
    "BacktestResult",
    "BotCandle",
    "Fill",
    "Order",
    "PaperPortfolio",
    "RiskConfig",
    "RiskDecision",
    "RiskManager",
    "Verdict",
    "compute_metrics",
    "compute_verdict",
    "run_paper_backtest",
]
