"""Historical OHLC replay simulator — strictly read-only.

The backtester replays real Kraken OHLC candles through the existing
deterministic engine (``features`` → ``strategies/ensemble`` →
``actionability`` → ``risk``) and simulates the resulting fills *locally*.

Crucial safety contract: this module **never** places paper or live orders.
It does not import ``src.execution`` and never invokes any Kraken CLI mutating
command. Every output is labelled ``backtest_local_estimate`` so downstream
consumers (dashboard, JSON exports, DB) can distinguish historical estimates
from real paper/live executions.

Workflow
--------
1. ``parse_ohlc_rows`` normalises raw OHLC payloads (already pre-processed by
   ``kraken_cli.fetch_ohlc`` or test fixtures) into :class:`Candle` records.
2. ``build_replay_candles`` returns the canonical chronological list.
3. ``compute_replay_features`` builds a :class:`Features` snapshot from a
   sliding window plus a synthetic ticker derived from the last candle.
4. ``simulate_symbol`` walks the candle list and produces a :class:`SymbolResult`.
5. ``simulate_portfolio`` aggregates several symbols into a :class:`PortfolioResult`.
6. ``run_grid_search`` evaluates the configurations supplied by the script
   against the same OHLC payload and returns a :class:`GridResult`.

Shorting is explicitly disabled: a SELL signal without an open long position
results in HOLD (matching the live actionability gate). FIFO accounting is
used so that early lots are consumed first.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

from . import actionability as actionability_mod
from . import exit_rules as exit_rules_mod
from . import features as features_mod
from . import risk as risk_mod
from .config import Settings, YAMLConfig, get_settings
from .schemas import (
    Action,
    EnsembleResult,
    Features,
    PortfolioSnapshot,
    Position,
    StrategyVote,
)
from .sessions import (
    MarketSession,
    NY_TZ,
    _parse_iso_to_utc,
    classify_market_session,
)
from .strategies import breakout_score, combine, mean_reversion_score, momentum_score
from .utils import safe_float, utc_now_iso

SOURCE_LABEL = "backtest_local_estimate"
MARKET_HOURS_REPORT_KIND = "market_hours"
MIN_WARMUP_CANDLES = 4
_LIQUIDITY_VOLUME_TARGET = 5_000.0
_LIQUIDITY_BLOCK_THRESHOLD = 0.05


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Candle:
    """Canonical OHLC record consumed by the simulator."""

    timestamp_utc: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: Optional[float] = None
    trade_count: Optional[int] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp_utc,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": self.vwap,
            "trade_count": self.trade_count,
        }


@dataclass
class SimulatedTrade:
    timestamp_utc: str
    symbol: str
    side: Action
    price: float
    qty: float
    pnl: float = 0.0
    reason: str = ""
    cash_after: float = 0.0
    equity_after: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "symbol": self.symbol,
            "side": self.side,
            "price": round(self.price, 6),
            "qty": round(self.qty, 8),
            "pnl": round(self.pnl, 6),
            "reason": self.reason,
            "cash_after": round(self.cash_after, 4),
            "equity_after": round(self.equity_after, 4),
            "source": SOURCE_LABEL,
        }


@dataclass
class SimulationDecision:
    """Per-candle decision audit log used by the market-hours analysis.

    Populated only when ``simulate_symbol`` is called with
    ``record_decisions=True`` so the regular backtest output stays
    compact. The market-hours report consumes these entries to attribute
    blocks (``confidence`` / ``spread`` / ``low_liquidity``) to the
    correct US trading session.
    """

    timestamp_utc: str
    symbol: str
    action: str
    approved: bool
    actionability_reason: str
    risk_reasons: list[str]
    spread_bps: float
    volume: float
    liquidity_score: float
    realized_pnl: float = 0.0
    cash_after: float = 0.0
    equity_after: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp_utc": self.timestamp_utc,
            "symbol": self.symbol,
            "action": self.action,
            "approved": self.approved,
            "actionability_reason": self.actionability_reason,
            "risk_reasons": list(self.risk_reasons),
            "spread_bps": round(self.spread_bps, 4),
            "volume": round(self.volume, 4),
            "liquidity_score": round(self.liquidity_score, 4),
            "realized_pnl": round(self.realized_pnl, 6),
            "cash_after": round(self.cash_after, 4),
            "equity_after": round(self.equity_after, 4),
        }


@dataclass
class SymbolResult:
    symbol: str
    candles_used: int = 0
    initial_cash: float = 0.0
    final_cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    actionability_reasons: Counter = field(default_factory=Counter)
    risk_reasons: Counter = field(default_factory=Counter)
    trades: list[SimulatedTrade] = field(default_factory=list)
    decisions: list[SimulationDecision] = field(default_factory=list)
    last_price: float = 0.0
    open_quantity: float = 0.0
    avg_entry_price: float = 0.0
    status: str = "ok"
    note: str = ""
    source: str = SOURCE_LABEL

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "symbol": self.symbol,
            "candles_used": self.candles_used,
            "initial_cash": round(self.initial_cash, 4),
            "final_cash": round(self.final_cash, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "net_pnl": round(self.net_pnl, 4),
            "net_pnl_pct": round(self.net_pnl_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "trades_count": self.trades_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "hold_count": self.hold_count,
            "actionability_reasons_top": [
                {"reason": r, "count": c}
                for r, c in self.actionability_reasons.most_common(10)
            ],
            "risk_reasons_top": [
                {"reason": r, "count": c}
                for r, c in self.risk_reasons.most_common(10)
            ],
            "trades": [t.to_dict() for t in self.trades],
            "last_price": round(self.last_price, 6),
            "open_quantity": round(self.open_quantity, 8),
            "avg_entry_price": round(self.avg_entry_price, 6),
            "status": self.status,
            "note": self.note,
            "source": self.source,
        }
        # Decisions are kept off the default JSON payload (they can be
        # large) and only surfaced when explicitly populated.
        if self.decisions:
            out["decisions_count"] = len(self.decisions)
        return out


@dataclass
class PortfolioResult:
    initial_cash: float = 0.0
    final_cash: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    equity_final: float = 0.0
    trades_count: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    actionability_reasons_top: list[tuple[str, int]] = field(default_factory=list)
    risk_reasons_top: list[tuple[str, int]] = field(default_factory=list)
    best_symbol: Optional[str] = None
    worst_symbol: Optional[str] = None
    by_symbol: dict[str, SymbolResult] = field(default_factory=dict)
    status: str = "ok"
    note: str = ""
    source: str = SOURCE_LABEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "initial_cash": round(self.initial_cash, 4),
            "final_cash": round(self.final_cash, 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "unrealized_pnl": round(self.unrealized_pnl, 4),
            "net_pnl": round(self.net_pnl, 4),
            "net_pnl_pct": round(self.net_pnl_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "equity_final": round(self.equity_final, 4),
            "trades_count": self.trades_count,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate": round(self.win_rate, 4),
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "hold_count": self.hold_count,
            "actionability_reasons_top": [
                {"reason": r, "count": c} for r, c in self.actionability_reasons_top
            ],
            "risk_reasons_top": [
                {"reason": r, "count": c} for r, c in self.risk_reasons_top
            ],
            "best_symbol": self.best_symbol,
            "worst_symbol": self.worst_symbol,
            "by_symbol": {sym: res.to_dict() for sym, res in self.by_symbol.items()},
            "status": self.status,
            "note": self.note,
            "source": self.source,
        }


@dataclass
class GridConfigResult:
    overrides: dict[str, Any]
    portfolio: PortfolioResult
    adjusted_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "overrides": dict(self.overrides),
            "adjusted_score": round(self.adjusted_score, 6),
            "net_pnl_pct": round(self.portfolio.net_pnl_pct, 6),
            "max_drawdown_pct": round(self.portfolio.max_drawdown_pct, 6),
            "trades_count": self.portfolio.trades_count,
            "win_rate": round(self.portfolio.win_rate, 4),
            "buy_count": self.portfolio.buy_count,
            "sell_count": self.portfolio.sell_count,
            "hold_count": self.portfolio.hold_count,
            "source": SOURCE_LABEL,
        }


@dataclass
class GridResult:
    combos_evaluated: int = 0
    duration_seconds: float = 0.0
    top_by_adjusted_score: list[GridConfigResult] = field(default_factory=list)
    best_by_adjusted_score: Optional[GridConfigResult] = None
    best_by_net_pnl_pct: Optional[GridConfigResult] = None
    cautious_recommendation: Optional[dict[str, Any]] = None
    source: str = SOURCE_LABEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "combos_evaluated": self.combos_evaluated,
            "duration_seconds": round(self.duration_seconds, 3),
            "top_by_adjusted_score": [c.to_dict() for c in self.top_by_adjusted_score],
            "best_by_adjusted_score": (
                self.best_by_adjusted_score.to_dict()
                if self.best_by_adjusted_score
                else None
            ),
            "best_by_net_pnl_pct": (
                self.best_by_net_pnl_pct.to_dict()
                if self.best_by_net_pnl_pct
                else None
            ),
            "cautious_recommendation": self.cautious_recommendation,
            "source": self.source,
            "warning": (
                "Historical performance is not predictive of future results. "
                "backtest_local_estimate uses real OHLC data from Kraken CLI "
                "but simulates fills locally — no live or paper orders were placed."
            ),
        }


# ---------------------------------------------------------------------------
# Candle parsing
# ---------------------------------------------------------------------------


def _coerce_timestamp(raw: Any) -> str:
    """Best-effort ISO 8601 string from various Kraken CLI shapes."""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (int, float)):
        try:
            from datetime import datetime, timezone

            return (
                datetime.fromtimestamp(float(raw), tz=timezone.utc)
                .isoformat(timespec="seconds")
                .replace("+00:00", "Z")
            )
        except (OverflowError, OSError, ValueError):
            return str(raw)
    return str(raw)


def parse_ohlc_rows(symbol: str, raw_ohlc: Sequence[Any]) -> list[Candle]:
    """Normalise raw OHLC rows (lists or dicts) into :class:`Candle` records.

    Accepts both Kraken array form ``[ts, o, h, l, c, vwap, vol, trades?]``
    and the dict form already produced by ``kraken_cli.fetch_ohlc``.
    """
    if not raw_ohlc:
        return []
    parsed: list[Candle] = []
    for row in raw_ohlc:
        if isinstance(row, Candle):
            parsed.append(row)
            continue
        if isinstance(row, dict):
            ts = (
                row.get("timestamp")
                or row.get("timestamp_utc")
                or row.get("time")
                or row.get("t")
            )
            parsed.append(
                Candle(
                    timestamp_utc=_coerce_timestamp(ts),
                    open=safe_float(row.get("open")),
                    high=safe_float(row.get("high")),
                    low=safe_float(row.get("low")),
                    close=safe_float(row.get("close")),
                    volume=safe_float(row.get("volume")),
                    vwap=row.get("vwap") if row.get("vwap") is not None else None,
                    trade_count=(
                        int(row["trade_count"])
                        if row.get("trade_count") is not None
                        else (
                            int(row["trades"])
                            if row.get("trades") is not None
                            and isinstance(row.get("trades"), (int, float))
                            else None
                        )
                    ),
                )
            )
            continue
        if isinstance(row, (list, tuple)) and len(row) >= 5:
            parsed.append(
                Candle(
                    timestamp_utc=_coerce_timestamp(row[0]),
                    open=safe_float(row[1]),
                    high=safe_float(row[2]),
                    low=safe_float(row[3]),
                    close=safe_float(row[4]),
                    vwap=(safe_float(row[5]) if len(row) >= 6 else None),
                    volume=(safe_float(row[6]) if len(row) >= 7 else 0.0),
                    trade_count=(
                        int(row[7])
                        if len(row) >= 8 and row[7] is not None
                        else None
                    ),
                )
            )
    return parsed


def build_replay_candles(symbol: str, ohlc_rows: Sequence[Any]) -> list[Candle]:
    """Build the chronological candle list for a symbol replay."""
    parsed = parse_ohlc_rows(symbol, ohlc_rows)
    # Drop obviously broken rows (no close, no volume info, no timestamp).
    clean = [c for c in parsed if c.close > 0]
    return clean


# ---------------------------------------------------------------------------
# Feature snapshot
# ---------------------------------------------------------------------------


def _synthetic_ticker(symbol: str, window: Sequence[Candle]) -> dict[str, Any]:
    last = window[-1]
    spread = max(0.01, last.close * 0.0008)
    return {
        "pair": symbol,
        "ask": last.close + spread,
        "bid": last.close - spread,
        "last": last.close,
        "high_24h": max(c.high for c in window),
        "low_24h": min(c.low for c in window if c.low > 0),
        "open": window[0].open,
        "volume_24h": sum(c.volume for c in window),
        "source": SOURCE_LABEL,
    }


def compute_replay_features(
    symbol: str,
    candles_window: Sequence[Candle],
    config: Optional[YAMLConfig] = None,
    profile: Optional[str] = None,
    *,
    interval_minutes: int = 60,
) -> Optional[Features]:
    """Build a :class:`Features` snapshot from a sliding candle window.

    Returns ``None`` when the window is too small to compute the required
    multi-horizon returns — the simulator must skip the iteration cleanly.
    The ``config`` and ``profile`` arguments are kept for parity with the
    public API used by tests and callers; downstream feature computation is
    pure and does not consult them today.
    """
    if not candles_window or len(candles_window) < MIN_WARMUP_CANDLES:
        return None
    candle_dicts = [c.to_dict() for c in candles_window]
    ticker = _synthetic_ticker(symbol, candles_window)
    try:
        return features_mod.compute_features(
            symbol=symbol,
            ticker=ticker,
            candles=candle_dicts,
            candle_interval_minutes=interval_minutes,
        )
    except Exception:  # noqa: BLE001 — defensive: never crash a backtest cycle
        return None


# ---------------------------------------------------------------------------
# Settings overrides for the grid search
# ---------------------------------------------------------------------------


def _build_settings_override(
    base: Settings,
    *,
    overrides: Mapping[str, Any],
) -> Settings:
    """Return a new ``Settings`` instance with the requested overrides applied.

    Keys recognised by this helper (everything else is silently ignored —
    callers like the grid search and the walk-forward routine pass
    keys such as ``top_n`` / ``block_low_liquidity`` that are consumed
    further down the pipeline):

    - ``min_opportunity_score_buy`` / ``min_opportunity_score_sell``
      → ``settings.config.trading.*``
    - ``max_spread_bps`` → ``settings.config.risk.max_spread_bps``
    - ``min_confidence_to_trade`` → ``settings.config.strategy.*``
      (walk-forward grid knob)
    - ``max_hold_minutes`` → ``settings.config.exit.max_hold_minutes``
      (walk-forward grid knob — controls the time-stop exit rule).
      Also clears ``exit.time_stop_minutes`` so the grid value is the
      one the exit-rules engine reads (``time_stop_minutes`` is the
      crypto-profile alias that takes precedence in
      :func:`src.exit_rules._resolve_params` when set).
    - ``time_stop_minutes`` → ``settings.config.exit.time_stop_minutes``
      (crypto-profile alias of ``max_hold_minutes`` — gridding this
      key directly is more explicit than relying on the implicit
      override above).
    - ``stop_loss_pct`` / ``take_profit_pct`` →
      ``settings.config.risk.*`` (profile overrides win in
      :mod:`src.exit_rules` so this is the correct injection point)
    - ``block_low_liquidity=False`` → drops the LOW_LIQUIDITY regime
      from the risk gate (simulation-only; never mutates config.yaml).
    """
    cfg = base.config
    trading = cfg.trading.model_copy()
    risk_cfg = cfg.risk.model_copy()
    strategy_cfg = cfg.strategy.model_copy()
    exit_cfg = cfg.exit.model_copy()

    if "min_opportunity_score_buy" in overrides:
        trading.min_opportunity_score_buy = float(overrides["min_opportunity_score_buy"])
    if "min_opportunity_score_sell" in overrides:
        trading.min_opportunity_score_sell = float(overrides["min_opportunity_score_sell"])
    if "max_spread_bps" in overrides:
        risk_cfg.max_spread_bps = int(overrides["max_spread_bps"])
    if "min_confidence_to_trade" in overrides:
        strategy_cfg.min_confidence_to_trade = float(overrides["min_confidence_to_trade"])
    if "max_hold_minutes" in overrides:
        exit_cfg.max_hold_minutes = float(overrides["max_hold_minutes"])
        # ``time_stop_minutes`` takes precedence over ``max_hold_minutes``
        # in :func:`src.exit_rules._resolve_params` when set, so clearing
        # it here ensures the grid value is the one the exit engine
        # actually reads (crypto-profile shadowing safety).
        exit_cfg.time_stop_minutes = None
    if "time_stop_minutes" in overrides:
        exit_cfg.time_stop_minutes = float(overrides["time_stop_minutes"])
    if "stop_loss_pct" in overrides:
        risk_cfg.stop_loss_pct = float(overrides["stop_loss_pct"])
    if "take_profit_pct" in overrides:
        risk_cfg.take_profit_pct = float(overrides["take_profit_pct"])

    # Simulation-only: when block_low_liquidity is explicitly False we
    # also drop the LOW_LIQUIDITY regime gate so a thin xStocks book
    # is no longer unconditionally rejected by the risk layer. The
    # override never reaches config.yaml.
    block_low_liquidity = overrides.get("block_low_liquidity", True)
    if block_low_liquidity is False:
        risk_cfg.block_if_regime = [
            r for r in risk_cfg.block_if_regime if r != "LOW_LIQUIDITY"
        ]

    updated_cfg = cfg.model_copy(update={
        "trading": trading,
        "risk": risk_cfg,
        "strategy": strategy_cfg,
        "exit": exit_cfg,
    })
    return base.model_copy(update={"config": updated_cfg})


# ---------------------------------------------------------------------------
# Simulator state
# ---------------------------------------------------------------------------


@dataclass
class _Lot:
    qty: float
    price: float


@dataclass
class _SimState:
    """Internal mutable state for a single-symbol replay."""

    cash: float
    lots: list[_Lot] = field(default_factory=list)
    realized_pnl: float = 0.0
    peak_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    opened_at: Optional[str] = None

    @property
    def quantity(self) -> float:
        return sum(lot.qty for lot in self.lots)

    @property
    def avg_entry(self) -> float:
        total_qty = self.quantity
        if total_qty <= 0:
            return 0.0
        return sum(lot.qty * lot.price for lot in self.lots) / total_qty

    def notional(self, mark: float) -> float:
        return self.quantity * mark

    def unrealized(self, mark: float) -> float:
        return sum(lot.qty * (mark - lot.price) for lot in self.lots)

    def equity(self, mark: float) -> float:
        return self.cash + self.notional(mark)

    def update_drawdown(self, mark: float) -> None:
        eq = self.equity(mark)
        if eq > self.peak_equity:
            self.peak_equity = eq
        if self.peak_equity > 0:
            dd = max(0.0, (self.peak_equity - eq) / self.peak_equity * 100.0)
            if dd > self.max_drawdown_pct:
                self.max_drawdown_pct = dd

    def buy(self, *, qty: float, price: float, timestamp_utc: Optional[str] = None) -> None:
        if qty <= 0 or price <= 0:
            return
        was_flat = self.quantity <= 1e-9
        cost = qty * price
        self.cash -= cost
        self.lots.append(_Lot(qty=qty, price=price))
        if was_flat and timestamp_utc:
            # Open the timing window for exit_rules (time_exit needs this).
            self.opened_at = timestamp_utc

    def sell_fifo(self, *, qty: float, price: float) -> tuple[float, float]:
        """Sell ``qty`` (clamped to open quantity) using FIFO. Returns
        ``(filled_qty, realized_pnl_for_this_trade)``."""
        if qty <= 0 or price <= 0 or not self.lots:
            return 0.0, 0.0
        remaining = min(qty, self.quantity)
        filled = remaining
        pnl_trade = 0.0
        while remaining > 1e-12 and self.lots:
            lot = self.lots[0]
            take = min(lot.qty, remaining)
            pnl_trade += take * (price - lot.price)
            lot.qty -= take
            remaining -= take
            if lot.qty <= 1e-12:
                self.lots.pop(0)
        self.realized_pnl += pnl_trade
        self.cash += filled * price
        if self.quantity <= 1e-9:
            self.opened_at = None
        return filled, pnl_trade


# ---------------------------------------------------------------------------
# Per-symbol simulation
# ---------------------------------------------------------------------------


def _liquidity_score_from_features(features: Features) -> float:
    """Cheap liquidity proxy from the Features snapshot.

    Combines normalised volume (vs ``_LIQUIDITY_VOLUME_TARGET``) and a spread
    penalty so the actionability / block_low_liquidity gates have a value to
    work with even without a real orderbook.
    """
    vol = features.volume_1h
    vol_norm = max(0.0, min(1.0, vol / max(_LIQUIDITY_VOLUME_TARGET, 1.0)))
    spread = features.spread_bps
    spread_norm = max(0.0, min(1.0, 1.0 - spread / 80.0))
    score = 0.7 * vol_norm + 0.3 * spread_norm
    return max(0.0, min(1.0, score))


def _vote_for(features: Features) -> list[StrategyVote]:
    return [
        momentum_score(features),
        breakout_score(features),
        mean_reversion_score(features),
    ]


def _build_simulated_snapshot(symbol: str, state: _SimState, mark: float) -> PortfolioSnapshot:
    if state.quantity <= 0:
        return PortfolioSnapshot(cash_usd=state.cash, equity_usd=state.equity(mark))
    pos = Position(
        symbol=symbol,
        quantity=state.quantity,
        avg_entry_price=state.avg_entry,
        market_price=mark,
        notional_usd=state.notional(mark),
        unrealized_pnl_usd=state.unrealized(mark),
        realized_pnl_usd=state.realized_pnl,
        opened_at=state.opened_at,
    )
    return PortfolioSnapshot(
        cash_usd=state.cash,
        equity_usd=state.equity(mark),
        positions=[pos],
    )


def simulate_symbol(
    symbol: str,
    candles: Sequence[Candle],
    config: Optional[YAMLConfig] = None,
    profile: Optional[str] = None,
    initial_cash: float = 10_000.0,
    *,
    settings: Optional[Settings] = None,
    block_low_liquidity: Optional[bool] = None,
    interval_minutes: int = 60,
    record_decisions: bool = False,
    disable_realtime_cooldown: bool = False,
) -> SymbolResult:
    """Replay a single symbol through the deterministic decision pipeline.

    Parameters
    ----------
    symbol:
        Ticker (e.g. ``"NVDAx"``). Used in logs and snapshots only.
    candles:
        Chronological list of :class:`Candle` rows.
    config / profile:
        Kept for API parity. The active ``Settings`` (real or overridden)
        carries the live calibration knobs.
    initial_cash:
        Starting USD balance for the simulated ledger.
    settings:
        Optional overridden :class:`Settings`. When ``None``, the cached
        global settings are used. Grid search supplies a tweaked copy.
    block_low_liquidity:
        Simulation-only flag: when True, suppress BUY when the liquidity
        proxy is below ``_LIQUIDITY_BLOCK_THRESHOLD``. Defaults to True.
    disable_realtime_cooldown:
        Simulation-only flag. The risk layer's per-symbol cooldown uses
        ``time.time()`` (wall clock) which does not advance with replayed
        candles, so a single BUY effectively blocks every subsequent BUY
        on the same symbol for the rest of the run. When True, the
        cooldown gate is forced open on the cloned settings only — live
        and paper paths are unaffected. Defaults to False to preserve
        exact historical behaviour.
    """
    s = settings or get_settings()
    block_low_liq = True if block_low_liquidity is None else bool(block_low_liquidity)

    # The risk layer measures drawdown against
    # ``competition.starting_equity_usd``. The simulator allocates an
    # equal slice of the global cash to every symbol, so we rebase the
    # competition starting equity to the per-symbol slice for this
    # simulation only — otherwise the drawdown gate fires on the very
    # first candle and rejects every BUY/SELL.
    if initial_cash > 0:
        comp = s.config.competition.model_copy(update={
            "starting_equity_usd": float(initial_cash),
        })
        s = s.model_copy(update={"config": s.config.model_copy(update={"competition": comp})})

    if disable_realtime_cooldown:
        risk_cfg = s.config.risk.model_copy(update={"cooldown_seconds_per_symbol": 0})
        s = s.model_copy(update={"config": s.config.model_copy(update={"risk": risk_cfg})})
    result = SymbolResult(
        symbol=symbol,
        initial_cash=initial_cash,
        final_cash=initial_cash,
        candles_used=len(candles),
    )
    if not candles:
        result.status = "no_data"
        result.note = "no candles supplied"
        return result

    # Reset risk cooldowns so the simulation starts from a clean slate even if
    # a previous backtest run touched the global state.
    risk_mod.reset_cooldowns()

    state = _SimState(cash=initial_cash, peak_equity=initial_cash)
    last_close = candles[-1].close
    actionable_seen = False

    def _log(
        *,
        current: Candle,
        action: str,
        approved: bool,
        actionability_reason: str,
        risk_reasons: Sequence[str],
        spread_bps: float,
        liquidity_score: float,
        realized_pnl: float = 0.0,
    ) -> None:
        if not record_decisions:
            return
        result.decisions.append(
            SimulationDecision(
                timestamp_utc=current.timestamp_utc,
                symbol=symbol,
                action=action,
                approved=approved,
                actionability_reason=actionability_reason or "",
                risk_reasons=list(risk_reasons),
                spread_bps=float(spread_bps),
                volume=float(current.volume),
                liquidity_score=float(liquidity_score),
                realized_pnl=float(realized_pnl),
                cash_after=float(state.cash),
                equity_after=float(state.equity(current.close)),
            )
        )

    for idx in range(MIN_WARMUP_CANDLES, len(candles)):
        window = candles[: idx + 1]
        current = candles[idx]
        feats = compute_replay_features(
            symbol, window, config=s.config, profile=profile, interval_minutes=interval_minutes
        )
        if feats is None:
            result.hold_count += 1
            result.actionability_reasons["no_features"] += 1
            _log(
                current=current,
                action="HOLD",
                approved=False,
                actionability_reason="no_features",
                risk_reasons=[],
                spread_bps=0.0,
                liquidity_score=0.0,
            )
            continue

        liquidity_score = _liquidity_score_from_features(feats)
        votes = _vote_for(feats)
        try:
            raw_ensemble: EnsembleResult = combine(
                features=feats, votes=votes, liquidity_score=liquidity_score
            )
        except Exception as exc:  # noqa: BLE001
            result.hold_count += 1
            err_reason = f"ensemble_error:{type(exc).__name__}"
            result.actionability_reasons[err_reason] += 1
            _log(
                current=current,
                action="HOLD",
                approved=False,
                actionability_reason=err_reason,
                risk_reasons=[],
                spread_bps=feats.spread_bps,
                liquidity_score=liquidity_score,
            )
            continue

        snapshot = _build_simulated_snapshot(symbol, state, mark=current.close)
        open_position = snapshot.positions[0] if snapshot.positions else None
        ensemble, actionability = actionability_mod.apply_actionability_gates(
            ensemble=raw_ensemble,
            features=feats,
            position=open_position,
            liquidity_score=liquidity_score,
            settings=s,
        )
        result.actionability_reasons[actionability.reason or "n/a"] += 1

        # Exit-rules engine: convert HOLD/BUY to SELL when a rule fires
        # against the current open long. The simulator mirrors the live
        # loop (see src/main.py::_apply_exit_rules_and_session_guard) so
        # backtest BUY/SELL counts now reflect the deployed gates.
        if open_position is not None and state.quantity > 1e-9:
            try:
                now_dt = _parse_iso_to_utc(current.timestamp_utc)
            except ValueError:
                now_dt = None
            exit_decision = exit_rules_mod.evaluate_exit_rules(
                position=open_position,
                current_price=float(current.close),
                opportunity_score=float(ensemble.final_score),
                now=now_dt,
                config=s.config,
            )
            if exit_decision.should_exit and exit_decision.rule:
                max_notional = state.quantity * max(current.close, 0.01)
                ensemble = ensemble.model_copy(
                    update={
                        "action": "SELL",
                        "suggested_size_usd": max_notional,
                        "rationale": (
                            f"{ensemble.rationale} | exit_rule={exit_decision.rule}: "
                            f"{exit_decision.reason}"
                        ).strip(" |"),
                    }
                )
                actionability = actionability.model_copy(
                    update={
                        "buy_eligible": False,
                        "sell_eligible": True,
                        "reason": f"exit_rule_{exit_decision.rule}",
                    }
                )
                result.actionability_reasons[
                    f"exit_rule_{exit_decision.rule}"
                ] += 1

        # Simulation-only liquidity guard. We never mutate config.yaml; this
        # mirrors a hypothetical risk gate the user might enable.
        if (
            block_low_liq
            and ensemble.action == "BUY"
            and liquidity_score < _LIQUIDITY_BLOCK_THRESHOLD
        ):
            result.hold_count += 1
            result.risk_reasons["block_low_liquidity"] += 1
            state.update_drawdown(current.close)
            _log(
                current=current,
                action="HOLD",
                approved=False,
                actionability_reason=actionability.reason or "n/a",
                risk_reasons=["block_low_liquidity"],
                spread_bps=feats.spread_bps,
                liquidity_score=liquidity_score,
            )
            continue

        is_exit_action = bool(
            ensemble.action == "SELL"
            and isinstance(actionability.reason, str)
            and actionability.reason.startswith("exit_rule_")
        )
        risk_result = risk_mod.evaluate_risk(
            ensemble=ensemble,
            features=feats,
            portfolio=snapshot,
            settings=s,
            intended_mode="dry_run",
            is_exit_action=is_exit_action,
        )
        for r in risk_result.reasons:
            result.risk_reasons[r] += 1

        if ensemble.action == "HOLD" or not risk_result.approved:
            result.hold_count += 1
            state.update_drawdown(current.close)
            _log(
                current=current,
                action="HOLD",
                approved=False,
                actionability_reason=actionability.reason or "n/a",
                risk_reasons=list(risk_result.reasons),
                spread_bps=feats.spread_bps,
                liquidity_score=liquidity_score,
            )
            continue

        actionable_seen = True
        price = current.close
        size_usd = max(0.0, float(risk_result.adjusted_size_usd or 0.0))
        if ensemble.action == "BUY":
            available_cash = max(0.0, state.cash)
            size_usd = min(size_usd, available_cash)
            qty = size_usd / price if price > 0 else 0.0
            if qty <= 0:
                result.hold_count += 1
                result.risk_reasons["insufficient_cash"] += 1
                _log(
                    current=current,
                    action="HOLD",
                    approved=False,
                    actionability_reason=actionability.reason or "n/a",
                    risk_reasons=["insufficient_cash"],
                    spread_bps=feats.spread_bps,
                    liquidity_score=liquidity_score,
                )
                continue
            state.buy(qty=qty, price=price, timestamp_utc=current.timestamp_utc)
            risk_mod.mark_traded(symbol)
            result.buy_count += 1
            result.trades.append(
                SimulatedTrade(
                    timestamp_utc=current.timestamp_utc,
                    symbol=symbol,
                    side="BUY",
                    price=price,
                    qty=qty,
                    pnl=0.0,
                    reason=actionability.reason or "buy_eligible",
                    cash_after=state.cash,
                    equity_after=state.equity(price),
                )
            )
            _log(
                current=current,
                action="BUY",
                approved=True,
                actionability_reason=actionability.reason or "buy_eligible",
                risk_reasons=[],
                spread_bps=feats.spread_bps,
                liquidity_score=liquidity_score,
                realized_pnl=0.0,
            )
        elif ensemble.action == "SELL":
            # Exit-only: clamp to open quantity. Shorting stays disabled.
            if state.quantity <= 0:
                result.hold_count += 1
                result.risk_reasons["sell_no_position"] += 1
                _log(
                    current=current,
                    action="HOLD",
                    approved=False,
                    actionability_reason=actionability.reason or "n/a",
                    risk_reasons=["sell_no_position"],
                    spread_bps=feats.spread_bps,
                    liquidity_score=liquidity_score,
                )
                continue
            target_qty = state.quantity
            if size_usd > 0 and price > 0:
                target_qty = min(state.quantity, size_usd / price)
            filled, pnl_trade = state.sell_fifo(qty=target_qty, price=price)
            if filled <= 0:
                result.hold_count += 1
                _log(
                    current=current,
                    action="HOLD",
                    approved=False,
                    actionability_reason=actionability.reason or "n/a",
                    risk_reasons=["sell_no_fill"],
                    spread_bps=feats.spread_bps,
                    liquidity_score=liquidity_score,
                )
                continue
            risk_mod.mark_traded(symbol)
            result.sell_count += 1
            if pnl_trade > 0:
                result.wins += 1
            elif pnl_trade < 0:
                result.losses += 1
            result.trades.append(
                SimulatedTrade(
                    timestamp_utc=current.timestamp_utc,
                    symbol=symbol,
                    side="SELL",
                    price=price,
                    qty=filled,
                    pnl=pnl_trade,
                    reason=actionability.reason or "sell_exit",
                    cash_after=state.cash,
                    equity_after=state.equity(price),
                )
            )
            _log(
                current=current,
                action="SELL",
                approved=True,
                actionability_reason=actionability.reason or "sell_exit",
                risk_reasons=[],
                spread_bps=feats.spread_bps,
                liquidity_score=liquidity_score,
                realized_pnl=pnl_trade,
            )

        state.update_drawdown(current.close)

    # Final mark-to-market.
    last_close = candles[-1].close
    state.update_drawdown(last_close)
    realized = state.realized_pnl
    unrealized = state.unrealized(last_close)
    net = realized + unrealized
    result.final_cash = state.cash
    result.realized_pnl = realized
    result.unrealized_pnl = unrealized
    result.net_pnl = net
    result.net_pnl_pct = (net / initial_cash * 100.0) if initial_cash > 0 else 0.0
    result.max_drawdown_pct = state.max_drawdown_pct
    result.trades_count = result.buy_count + result.sell_count
    result.win_rate = (
        result.wins / (result.wins + result.losses)
        if (result.wins + result.losses) > 0
        else 0.0
    )
    result.last_price = last_close
    result.open_quantity = state.quantity
    result.avg_entry_price = state.avg_entry
    if not actionable_seen and result.trades_count == 0:
        result.status = "all_hold"
        result.note = "no actionable signal across the replay window"
    return result


# ---------------------------------------------------------------------------
# Portfolio aggregation
# ---------------------------------------------------------------------------


def _split_cash(initial_cash: float, n: int) -> float:
    if n <= 0:
        return 0.0
    return float(initial_cash) / float(n)


def simulate_portfolio(
    symbols: Sequence[str],
    ohlc_by_symbol: Mapping[str, Sequence[Any]],
    config: Optional[YAMLConfig] = None,
    profile: Optional[str] = None,
    initial_cash: float = 10_000.0,
    *,
    settings: Optional[Settings] = None,
    overrides: Optional[Mapping[str, Any]] = None,
    interval_minutes: int = 60,
    record_decisions: bool = False,
    disable_realtime_cooldown: bool = False,
) -> PortfolioResult:
    """Run :func:`simulate_symbol` for each symbol and aggregate the results.

    The starting capital is split evenly across symbols (independent ledgers)
    so per-symbol PnL is comparable. ``overrides`` may contain grid-search
    overrides; ``block_low_liquidity`` is consumed by the simulator and the
    other knobs are applied to a fresh ``Settings`` copy.
    """
    base_settings = settings or get_settings()
    overrides = dict(overrides or {})
    sim_settings = _build_settings_override(base_settings, overrides=overrides)
    block_low_liquidity = overrides.get("block_low_liquidity", True)
    per_symbol_cash = _split_cash(initial_cash, len(symbols))

    by_symbol: dict[str, SymbolResult] = {}
    for sym in symbols:
        rows = ohlc_by_symbol.get(sym) or []
        candles = build_replay_candles(sym, rows)
        result = simulate_symbol(
            sym,
            candles,
            config=sim_settings.config,
            profile=profile,
            initial_cash=per_symbol_cash,
            settings=sim_settings,
            block_low_liquidity=bool(block_low_liquidity),
            interval_minutes=interval_minutes,
            record_decisions=record_decisions,
            disable_realtime_cooldown=disable_realtime_cooldown,
        )
        by_symbol[sym] = result

    aggregate = PortfolioResult(initial_cash=initial_cash)
    aggregate.by_symbol = by_symbol
    if not by_symbol:
        aggregate.status = "no_data"
        aggregate.note = "no symbols simulated"
        aggregate.final_cash = initial_cash
        aggregate.equity_final = initial_cash
        return aggregate

    realized = 0.0
    unrealized = 0.0
    final_cash = 0.0
    trades = 0
    wins = 0
    losses = 0
    buys = 0
    sells = 0
    holds = 0
    act_reasons: Counter = Counter()
    risk_reasons: Counter = Counter()
    drawdowns: list[float] = []
    best_sym: Optional[str] = None
    worst_sym: Optional[str] = None
    best_score = -math.inf
    worst_score = math.inf
    for sym, res in by_symbol.items():
        realized += res.realized_pnl
        unrealized += res.unrealized_pnl
        final_cash += res.final_cash
        trades += res.trades_count
        wins += res.wins
        losses += res.losses
        buys += res.buy_count
        sells += res.sell_count
        holds += res.hold_count
        act_reasons.update(res.actionability_reasons)
        risk_reasons.update(res.risk_reasons)
        drawdowns.append(res.max_drawdown_pct)
        if res.net_pnl_pct > best_score:
            best_score = res.net_pnl_pct
            best_sym = sym
        if res.net_pnl_pct < worst_score:
            worst_score = res.net_pnl_pct
            worst_sym = sym

    aggregate.realized_pnl = realized
    aggregate.unrealized_pnl = unrealized
    aggregate.net_pnl = realized + unrealized
    aggregate.final_cash = final_cash
    aggregate.equity_final = final_cash + sum(
        (res.last_price * res.open_quantity) for res in by_symbol.values()
    )
    aggregate.net_pnl_pct = (
        aggregate.net_pnl / initial_cash * 100.0 if initial_cash > 0 else 0.0
    )
    aggregate.max_drawdown_pct = max(drawdowns) if drawdowns else 0.0
    aggregate.trades_count = trades
    aggregate.wins = wins
    aggregate.losses = losses
    aggregate.win_rate = (
        wins / (wins + losses) if (wins + losses) > 0 else 0.0
    )
    aggregate.buy_count = buys
    aggregate.sell_count = sells
    aggregate.hold_count = holds
    aggregate.actionability_reasons_top = act_reasons.most_common(10)
    aggregate.risk_reasons_top = risk_reasons.most_common(10)
    aggregate.best_symbol = best_sym
    aggregate.worst_symbol = worst_sym
    return aggregate


# ---------------------------------------------------------------------------
# Grid search
# ---------------------------------------------------------------------------


def _expand_grid(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of the grid values, preserving key order."""
    keys = list(grid.keys())
    if not keys:
        return [dict()]
    combos: list[dict[str, Any]] = [dict()]
    for key in keys:
        values = list(grid[key])
        new_combos: list[dict[str, Any]] = []
        for c in combos:
            for v in values:
                merged = dict(c)
                merged[key] = v
                new_combos.append(merged)
        combos = new_combos
    return combos


def _adjusted_score(pf: PortfolioResult) -> float:
    return pf.net_pnl_pct - 0.5 * pf.max_drawdown_pct


def _pick_cautious(top: Sequence[GridConfigResult]) -> Optional[dict[str, Any]]:
    """Pick a robust config: lowest drawdown among the top quartile."""
    if not top:
        return None
    # Top 25% by adjusted_score, drop configs with no trades to avoid HOLD-only
    # winners "by default".
    head = list(top[: max(1, len(top) // 4)])
    active = [c for c in head if c.portfolio.trades_count > 0]
    pool = active if active else head
    cautious = min(pool, key=lambda c: (c.portfolio.max_drawdown_pct, -c.adjusted_score))
    return {
        "overrides": dict(cautious.overrides),
        "adjusted_score": round(cautious.adjusted_score, 6),
        "net_pnl_pct": round(cautious.portfolio.net_pnl_pct, 6),
        "max_drawdown_pct": round(cautious.portfolio.max_drawdown_pct, 6),
        "trades_count": cautious.portfolio.trades_count,
        "rationale": (
            "Lowest max_drawdown_pct among the top quartile by adjusted_score; "
            "preferred for live-session calibration where stability matters."
        ),
    }


def run_grid_search(
    symbols: Sequence[str],
    ohlc_by_symbol: Mapping[str, Sequence[Any]],
    config: Optional[YAMLConfig] = None,
    profile: Optional[str] = None,
    grid: Optional[Mapping[str, Sequence[Any]]] = None,
    *,
    initial_cash: float = 10_000.0,
    settings: Optional[Settings] = None,
    interval_minutes: int = 60,
    top_n_report: int = 10,
    max_combos: Optional[int] = None,
) -> GridResult:
    """Evaluate ``grid`` combos and return the ranked top configs.

    ``grid`` defaults to the calibration grid documented in the project
    plan. ``max_combos`` allows callers to cap the cartesian product (the
    grid is sampled by even striding when needed).
    """
    import time as _time

    grid = grid or {}
    combos = _expand_grid(grid)
    if max_combos is not None and len(combos) > max_combos > 0:
        step = max(1, len(combos) // max_combos)
        combos = combos[::step][:max_combos]

    started = _time.time()
    base_settings = settings or get_settings()
    # ``top_n`` does not change simulator output (the symbol list is fixed
    # by the caller). We memoize the PortfolioResult per unique
    # simulation-relevant subset so combos differing only in ``top_n``
    # reuse the cached result.
    _sim_relevant_keys = (
        "min_opportunity_score_buy",
        "min_opportunity_score_sell",
        "max_spread_bps",
        "block_low_liquidity",
    )
    cache: dict[tuple, PortfolioResult] = {}
    evaluated: list[GridConfigResult] = []
    for overrides in combos:
        top_n = overrides.get("top_n")
        if isinstance(top_n, int) and top_n > 0:
            combo_symbols = list(symbols)[: top_n]
        else:
            combo_symbols = list(symbols)
        key = tuple(
            [overrides.get(k) for k in _sim_relevant_keys]
            + [tuple(combo_symbols)]
        )
        pf = cache.get(key)
        if pf is None:
            pf = simulate_portfolio(
                combo_symbols,
                ohlc_by_symbol,
                config=base_settings.config,
                profile=profile,
                initial_cash=initial_cash,
                settings=base_settings,
                overrides=overrides,
                interval_minutes=interval_minutes,
            )
            cache[key] = pf
        evaluated.append(
            GridConfigResult(
                overrides=overrides,
                portfolio=pf,
                adjusted_score=_adjusted_score(pf),
            )
        )

    evaluated.sort(key=lambda c: c.adjusted_score, reverse=True)
    top = evaluated[: max(1, int(top_n_report))]
    best_adj = evaluated[0] if evaluated else None
    best_pnl = max(evaluated, key=lambda c: c.portfolio.net_pnl_pct, default=None)
    cautious = _pick_cautious(top)
    return GridResult(
        combos_evaluated=len(evaluated),
        duration_seconds=_time.time() - started,
        top_by_adjusted_score=top,
        best_by_adjusted_score=best_adj,
        best_by_net_pnl_pct=best_pnl,
        cautious_recommendation=cautious,
    )


# ---------------------------------------------------------------------------
# Market sessions — strictly read-only, used by --market-hours-report
#
# ``MarketSession`` / ``classify_market_session`` / ``NY_TZ`` /
# ``_parse_iso_to_utc`` are re-exported from :mod:`src.sessions` so the
# agent loop, the backtester, and the live preflight all agree on one
# canonical session classifier.
# ---------------------------------------------------------------------------


def tag_candles_with_session(
    candles: Sequence[Candle],
) -> list[dict[str, Any]]:
    """Attach a :class:`MarketSession` to every candle.

    Returns a list of dicts ``{candle, session}`` so callers can iterate
    without re-parsing timestamps. Candles with malformed timestamps are
    silently dropped (the simulator already filters those upstream).
    """
    tagged: list[dict[str, Any]] = []
    for c in candles:
        try:
            ts = _parse_iso_to_utc(c.timestamp_utc)
        except ValueError:
            continue
        session = classify_market_session(ts)
        tagged.append({"candle": c, "session": session, "ts_utc": ts})
    return tagged


@dataclass
class SessionAggregate:
    """Per-session aggregate consumed by the market-hours report."""

    session: MarketSession
    candles_count: int = 0
    symbols_count: int = 0
    avg_volume: float = 0.0
    median_volume: float = 0.0
    avg_spread_bps: Optional[float] = None
    buy_count: int = 0
    sell_count: int = 0
    hold_count: int = 0
    approved_count: int = 0
    low_liquidity_blocks: int = 0
    confidence_blocks: int = 0
    spread_blocks: int = 0
    net_pnl: float = 0.0
    net_pnl_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    best_symbol: Optional[str] = None
    worst_symbol: Optional[str] = None
    top_rejection_reasons: list[tuple[str, int]] = field(default_factory=list)
    initial_cash_attribution: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session.value,
            "candles_count": self.candles_count,
            "symbols_count": self.symbols_count,
            "avg_volume": round(self.avg_volume, 4),
            "median_volume": round(self.median_volume, 4),
            "avg_spread_bps": (
                round(self.avg_spread_bps, 4)
                if self.avg_spread_bps is not None
                else None
            ),
            "buy_count": self.buy_count,
            "sell_count": self.sell_count,
            "hold_count": self.hold_count,
            "approved_count": self.approved_count,
            "low_liquidity_blocks": self.low_liquidity_blocks,
            "confidence_blocks": self.confidence_blocks,
            "spread_blocks": self.spread_blocks,
            "net_pnl": round(self.net_pnl, 4),
            "net_pnl_pct": round(self.net_pnl_pct, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "best_symbol": self.best_symbol,
            "worst_symbol": self.worst_symbol,
            "top_rejection_reasons": [
                {"reason": r, "count": c} for r, c in self.top_rejection_reasons
            ],
            "initial_cash_attribution": round(self.initial_cash_attribution, 4),
        }


def _classify_block_kind(reasons: Sequence[str]) -> set[str]:
    """Map one or more risk-reason strings to coarse block categories.

    Returns a *set* so the same decision can land in multiple buckets
    when several gates rejected at once (e.g. spread + confidence).
    """
    kinds: set[str] = set()
    for raw in reasons:
        r = (raw or "").lower()
        if not r:
            continue
        if "low_liquidity" in r or "block_low_liquidity" in r or "low liquidity" in r:
            kinds.add("low_liquidity")
        if "confidence" in r:
            kinds.add("confidence")
        if "spread" in r:
            kinds.add("spread")
    return kinds


def aggregate_by_session(
    portfolio_result: PortfolioResult,
    candles_by_symbol: Mapping[str, Sequence[Candle]],
) -> dict[MarketSession, SessionAggregate]:
    """Group simulator decisions and candles by US market session.

    The portfolio result must be produced with ``record_decisions=True``
    so the per-candle audit log is available. Candles missing a parseable
    timestamp are silently skipped (they have already been filtered by
    ``build_replay_candles``).
    """
    aggs: dict[MarketSession, SessionAggregate] = {
        s: SessionAggregate(session=s) for s in MarketSession
    }
    volumes_per_session: dict[MarketSession, list[float]] = {
        s: [] for s in MarketSession
    }
    spreads_per_session: dict[MarketSession, list[float]] = {
        s: [] for s in MarketSession
    }
    symbols_per_session: dict[MarketSession, set[str]] = {
        s: set() for s in MarketSession
    }
    pnl_per_session_per_symbol: dict[MarketSession, dict[str, float]] = {
        s: {} for s in MarketSession
    }
    rejection_per_session: dict[MarketSession, Counter] = {
        s: Counter() for s in MarketSession
    }
    equity_curves_per_session: dict[MarketSession, list[float]] = {
        s: [] for s in MarketSession
    }
    initial_cash_total = 0.0

    for symbol, sym_res in (portfolio_result.by_symbol or {}).items():
        candles = list(candles_by_symbol.get(symbol) or [])
        initial_cash_total += float(sym_res.initial_cash or 0.0)
        final_mark = float(sym_res.last_price or 0.0)
        for tagged in tag_candles_with_session(candles):
            session = tagged["session"]
            candle: Candle = tagged["candle"]
            aggs[session].candles_count += 1
            volumes_per_session[session].append(float(candle.volume))
            symbols_per_session[session].add(symbol)

        # Decisions are timestamped — they map cleanly to a session.
        for dec in sym_res.decisions or []:
            try:
                ts = _parse_iso_to_utc(dec.timestamp_utc)
            except ValueError:
                continue
            session = classify_market_session(ts)
            agg = aggs[session]
            symbols_per_session[session].add(symbol)
            spreads_per_session[session].append(float(dec.spread_bps))
            equity_curves_per_session[session].append(float(dec.equity_after))
            if dec.action == "BUY":
                agg.buy_count += 1
                if dec.approved:
                    agg.approved_count += 1
            elif dec.action == "SELL":
                agg.sell_count += 1
                if dec.approved:
                    agg.approved_count += 1
                # Note: realized PnL is attributed below from the
                # canonical ``trades`` list — using both would double
                # count the same fill.
            else:
                agg.hold_count += 1
            for reason in dec.risk_reasons or []:
                rejection_per_session[session][reason] += 1
            kinds = _classify_block_kind(dec.risk_reasons or [])
            if "low_liquidity" in kinds:
                agg.low_liquidity_blocks += 1
            if "confidence" in kinds:
                agg.confidence_blocks += 1
            if "spread" in kinds:
                agg.spread_blocks += 1

        # Per-trade contribution to per-session PnL. SELL trades carry
        # their own realized PnL; BUY trades are credited with their
        # mark-to-market contribution (qty × (final_price − entry)) to
        # the session in which they were filled. This way a session
        # that produced approved BUYs with no exit still surfaces a
        # meaningful net_pnl attribution.
        for trade in sym_res.trades or []:
            try:
                t_ts = _parse_iso_to_utc(trade.timestamp_utc)
            except ValueError:
                continue
            t_session = classify_market_session(t_ts)
            pnl_per_session_per_symbol[t_session].setdefault(symbol, 0.0)
            if trade.side == "SELL":
                pnl_per_session_per_symbol[t_session][symbol] += float(trade.pnl)
            elif trade.side == "BUY" and final_mark > 0 and trade.qty > 0:
                pnl_per_session_per_symbol[t_session][symbol] += float(
                    trade.qty * (final_mark - trade.price)
                )

    # Per-session aggregates: volumes, spreads, PnL, drawdown.
    for session, agg in aggs.items():
        vols = volumes_per_session[session]
        if vols:
            agg.avg_volume = sum(vols) / len(vols)
            agg.median_volume = float(statistics.median(vols))
        spreads = spreads_per_session[session]
        agg.avg_spread_bps = (sum(spreads) / len(spreads)) if spreads else None
        agg.symbols_count = len(symbols_per_session[session])
        per_sym = pnl_per_session_per_symbol[session]
        agg.net_pnl = float(sum(per_sym.values()))
        if per_sym:
            best = max(per_sym.items(), key=lambda kv: kv[1])
            worst = min(per_sym.items(), key=lambda kv: kv[1])
            agg.best_symbol = best[0]
            agg.worst_symbol = worst[0]
        # net_pnl_pct: attribute against the session's covered initial cash.
        # If we have decisions touching N symbols with equal cash slices,
        # use the sum of those slices as denominator. Fallback to total.
        cash_slice = 0.0
        for sym in symbols_per_session[session]:
            cash_slice += float(
                (portfolio_result.by_symbol or {})
                .get(sym, SymbolResult(symbol=sym))
                .initial_cash or 0.0
            )
        agg.initial_cash_attribution = cash_slice
        denom = cash_slice if cash_slice > 0 else initial_cash_total
        if denom > 0:
            agg.net_pnl_pct = agg.net_pnl / denom * 100.0
        # max_drawdown_pct restricted to the session's equity curve.
        curve = equity_curves_per_session[session]
        if curve:
            peak = curve[0]
            mdd = 0.0
            for eq in curve:
                if eq > peak:
                    peak = eq
                if peak > 0:
                    dd = max(0.0, (peak - eq) / peak * 100.0)
                    if dd > mdd:
                        mdd = dd
            agg.max_drawdown_pct = mdd
        agg.top_rejection_reasons = rejection_per_session[session].most_common(5)

    return aggs


# ---------------------------------------------------------------------------
# Helpers exposed to scripts / dashboard
# ---------------------------------------------------------------------------


def build_run_payload(
    *,
    symbols: Sequence[str],
    portfolio: PortfolioResult,
    grid: Optional[GridResult] = None,
    profile: Optional[str] = None,
    interval_minutes: int = 60,
    candles_per_symbol: Optional[Mapping[str, int]] = None,
    extras: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Compose the canonical JSON payload written to disk + DB.

    Every nested structure is tagged ``source=backtest_local_estimate`` so
    downstream consumers can audit the origin of the data.
    """
    payload: dict[str, Any] = {
        "generated_at": utc_now_iso(),
        "profile": profile,
        "interval_minutes": interval_minutes,
        "symbols": list(symbols),
        "candles_per_symbol": dict(candles_per_symbol or {}),
        "portfolio": portfolio.to_dict(),
        "source": SOURCE_LABEL,
        "warning": (
            "Historical performance is not predictive of future results. "
            "backtest_local_estimate uses real OHLC data from Kraken CLI "
            "but simulates fills locally — no live or paper orders were placed."
        ),
    }
    if grid is not None:
        payload["grid"] = grid.to_dict()
    if extras:
        payload.update(dict(extras))
    return payload


def _safe_div(num: float, den: float) -> float:
    return num / den if abs(den) > 1e-9 else 0.0


def _cest_window_for_session(session: MarketSession) -> str:
    """Human-friendly CEST window label for a US trading session.

    CEST is UTC+2; ET (EDT during DST) is UTC-4 → +6h offset. The
    table below is intentionally hard-coded for the report so the
    output stays readable even when DST shifts; the JSON payload
    keeps the canonical session enum.
    """
    table = {
        MarketSession.US_PREMARKET: "10:00–15:30 CEST (04:00–09:30 ET)",
        MarketSession.US_CORE: "15:30–22:00 CEST (09:30–16:00 ET)",
        MarketSession.US_AFTERHOURS: "22:00–02:00 CEST (16:00–20:00 ET)",
        MarketSession.OVERNIGHT: "02:00–10:00 CEST (20:00–04:00 ET)",
        MarketSession.WEEKEND: "weekend (NY local time)",
    }
    return table.get(session, str(session.value))


def _portfolio_totals(
    portfolio: PortfolioResult,
    sessions: Mapping[MarketSession, SessionAggregate],
) -> dict[str, Any]:
    """Compact totals block reused for variant summaries."""
    return {
        "net_pnl_pct": round(portfolio.net_pnl_pct, 4),
        "net_pnl": round(portfolio.net_pnl, 4),
        "trades_count": portfolio.trades_count,
        "buy_count": portfolio.buy_count,
        "sell_count": portfolio.sell_count,
        "hold_count": portfolio.hold_count,
        "max_drawdown_pct": round(portfolio.max_drawdown_pct, 4),
        "best_symbol": portfolio.best_symbol,
        "worst_symbol": portfolio.worst_symbol,
        "low_liquidity_blocks": sum(s.low_liquidity_blocks for s in sessions.values()),
        "confidence_blocks": sum(s.confidence_blocks for s in sessions.values()),
        "spread_blocks": sum(s.spread_blocks for s in sessions.values()),
        "win_rate": round(portfolio.win_rate, 4),
    }


def _best_window_for_recommendation(
    sessions: Mapping[MarketSession, SessionAggregate],
) -> tuple[Optional[MarketSession], float]:
    """Pick the session with the best risk-adjusted ratio (PnL / MDD)."""
    best: Optional[MarketSession] = None
    best_ratio = -math.inf
    for session, agg in sessions.items():
        if session == MarketSession.WEEKEND:
            continue
        if agg.net_pnl_pct == 0 and agg.max_drawdown_pct == 0:
            continue
        ratio = agg.net_pnl_pct / max(agg.max_drawdown_pct, 0.01)
        if ratio > best_ratio:
            best_ratio = ratio
            best = session
    return best, best_ratio if best is not None else 0.0


def _top_us_core_tickers(
    variant_results: Mapping[str, PortfolioResult],
    candles_by_symbol: Mapping[str, Sequence[Candle]],
    *,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Return up to ``limit`` symbols ranked by their US_CORE PnL footprint.

    The ranking is computed on the *blocking* variant (A) so the live
    runtime constraint is reflected; if A has no signal we fall back to
    the simulation-only variant (B). PnL is the sum of:
    - SELL trades fired in US_CORE (realized component), and
    - BUY trades fired in US_CORE marked-to-market against the symbol's
      last close (unrealized component for still-open positions).
    """
    out: list[tuple[str, float]] = []
    for variant_key in ("A_block_low_liquidity", "B_allow_low_liquidity_simulation_only"):
        portfolio = variant_results.get(variant_key)
        if portfolio is None:
            continue
        ranking: dict[str, float] = {}
        for sym, sym_res in (portfolio.by_symbol or {}).items():
            final_mark = float(sym_res.last_price or 0.0)
            score = 0.0
            for trade in sym_res.trades or []:
                try:
                    ts = _parse_iso_to_utc(trade.timestamp_utc)
                except ValueError:
                    continue
                if classify_market_session(ts) != MarketSession.US_CORE:
                    continue
                if trade.side == "SELL":
                    score += float(trade.pnl)
                elif trade.side == "BUY" and final_mark > 0 and trade.qty > 0:
                    score += float(trade.qty * (final_mark - trade.price))
            if abs(score) > 1e-9:
                ranking[sym] = score
        if ranking:
            ranked = sorted(ranking.items(), key=lambda kv: kv[1], reverse=True)
            out = ranked[:limit]
            break

    return [
        {
            "symbol": sym,
            "us_core_realized_pnl": round(score, 4),
        }
        for sym, score in out
    ]


def build_market_hours_report(
    *,
    symbols: Sequence[str],
    profile: Optional[str],
    interval_minutes: int,
    candles_by_symbol: Mapping[str, Sequence[Candle]],
    variant_a: PortfolioResult,
    variant_b: PortfolioResult,
) -> dict[str, Any]:
    """Compose the canonical market-hours JSON payload.

    Variant A enforces the simulator's ``block_low_liquidity`` gate
    (mirrors live/paper runtime). Variant B drops the LOW_LIQUIDITY
    regime gate **for backtest analysis only** — the runtime keeps
    the gate enforced regardless of what this report recommends.
    """
    sessions_a = aggregate_by_session(variant_a, candles_by_symbol)
    sessions_b = aggregate_by_session(variant_b, candles_by_symbol)

    # candles_per_session aggregated from the union of both variants
    # (they share the OHLC payload so the totals match).
    candles_total = 0
    candles_per_session: Counter = Counter()
    for sym in symbols:
        candles = list(candles_by_symbol.get(sym) or [])
        candles_total += len(candles)
        for tagged in tag_candles_with_session(candles):
            candles_per_session[tagged["session"].value] += 1

    totals_a = _portfolio_totals(variant_a, sessions_a)
    totals_b = _portfolio_totals(variant_b, sessions_b)

    by_session_delta: dict[str, dict[str, float]] = {}
    for session in MarketSession:
        a = sessions_a[session]
        b = sessions_b[session]
        by_session_delta[session.value] = {
            "delta_net_pnl_pct": round(b.net_pnl_pct - a.net_pnl_pct, 4),
            "delta_trades_count": (
                (b.buy_count + b.sell_count) - (a.buy_count + a.sell_count)
            ),
            "delta_max_drawdown_pct": round(
                b.max_drawdown_pct - a.max_drawdown_pct, 4
            ),
        }

    delta_net_pnl = totals_b["net_pnl_pct"] - totals_a["net_pnl_pct"]
    delta_trades = totals_b["trades_count"] - totals_a["trades_count"]
    delta_mdd = totals_b["max_drawdown_pct"] - totals_a["max_drawdown_pct"]

    # Recommendation logic — deterministic, no ML.
    keep_blocking = True
    allow_dry_run_only = False
    rationale_parts: list[str] = []
    if totals_a["net_pnl_pct"] >= totals_b["net_pnl_pct"] - 0.5:
        keep_blocking = True
        rationale_parts.append(
            "Variant A is within 0.5 pct of Variant B → keep blocking; "
            "the marginal PnL gain does not justify weakening the safety gate."
        )
    elif delta_net_pnl > 1.0 and delta_mdd > 0.5:
        keep_blocking = True
        allow_dry_run_only = True
        rationale_parts.append(
            "Variant B improves PnL by more than 1 pct but raises max drawdown "
            "by more than 0.5 pct → allow LOW_LIQUIDITY only inside backtest "
            "analysis (dry_run-only); live and paper paths keep the gate."
        )
    else:
        keep_blocking = True
        rationale_parts.append(
            "No statistically meaningful upside detected → keep blocking by default."
        )

    best_session_a, best_ratio_a = _best_window_for_recommendation(sessions_a)
    best_window_label = (
        _cest_window_for_session(best_session_a) if best_session_a else "n/a"
    )

    top_tickers = _top_us_core_tickers(
        {
            "A_block_low_liquidity": variant_a,
            "B_allow_low_liquidity_simulation_only": variant_b,
        },
        candles_by_symbol,
        limit=5,
    )

    payload: dict[str, Any] = {
        "source": SOURCE_LABEL,
        "report_kind": MARKET_HOURS_REPORT_KIND,
        "timestamp_utc": utc_now_iso(),
        "profile": profile,
        "symbols": list(symbols),
        "interval_min": int(interval_minutes),
        "candles_total": candles_total,
        "candles_per_session": {
            s.value: int(candles_per_session.get(s.value, 0)) for s in MarketSession
        },
        "variants": {
            "A_block_low_liquidity": {
                "by_session": {s.value: sessions_a[s].to_dict() for s in MarketSession},
                "totals": totals_a,
            },
            "B_allow_low_liquidity_simulation_only": {
                "by_session": {s.value: sessions_b[s].to_dict() for s in MarketSession},
                "totals": totals_b,
            },
        },
        "comparison": {
            "delta_net_pnl_pct": round(delta_net_pnl, 4),
            "delta_trades_count": int(delta_trades),
            "delta_max_drawdown_pct": round(delta_mdd, 4),
            "by_session_delta": by_session_delta,
        },
        "recommendation": {
            "keep_low_liquidity_blocking_in_runtime": bool(keep_blocking),
            "allow_in_paper_dry_run_only": bool(allow_dry_run_only),
            "best_window_cest": best_window_label,
            "best_window_session": (
                best_session_a.value if best_session_a else None
            ),
            "best_window_ratio": round(best_ratio_a, 4) if best_session_a else None,
            "best_tickers_for_1530_cest": top_tickers,
            "rationale": " ".join(rationale_parts),
        },
        "warning": (
            "Historical performance is not predictive of future results. "
            "Variant B is for backtest analysis only — LOW_LIQUIDITY blocking "
            "remains enforced in runtime live/paper paths."
        ),
    }
    return payload


__all__ = [
    "Candle",
    "SimulatedTrade",
    "SimulationDecision",
    "SymbolResult",
    "PortfolioResult",
    "GridConfigResult",
    "GridResult",
    "MarketSession",
    "SessionAggregate",
    "MIN_WARMUP_CANDLES",
    "SOURCE_LABEL",
    "MARKET_HOURS_REPORT_KIND",
    "NY_TZ",
    "parse_ohlc_rows",
    "build_replay_candles",
    "compute_replay_features",
    "simulate_symbol",
    "simulate_portfolio",
    "run_grid_search",
    "build_run_payload",
    "classify_market_session",
    "tag_candles_with_session",
    "aggregate_by_session",
    "build_market_hours_report",
]
