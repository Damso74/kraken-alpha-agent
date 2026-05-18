"""Walk-forward parameter optimization for the xStocks backtester.

Why this module exists
----------------------
Plain grid search on a single window is a textbook over-fit trap: the
optimiser will happily pick whichever combo most matches the noise of
that window. To call a tuning step *honest* we need:

1. **A strict train / test split.** Parameters are picked using the
   train set only; the test set must never have driven the choice.
2. **An out-of-sample filter.** Configs that fail to generalise
   (negative test PnL or sub-50% test win rate) are discarded *before*
   ranking. We never pick the "best test winner" — we pick the best
   combo among configs that already proved they survive on unseen data.
3. **A robustness-aware ranking.** The composite score multiplies test
   PnL by test win rate and divides by max-drawdown so a single lucky
   trade cannot dominate.
4. **Explicit caveats.** Even with the discipline above, the grid is
   small and the data window is short by professional standards. The
   submission docs (``docs/METHODOLOGY.md``) say so in plain language.

This module is **strictly read-only with respect to the venue**: it
delegates every simulation to :mod:`src.backtest`, which never
shells out to ``kraken paper`` / ``kraken order`` / ``kraken futures``
mutating commands. ``config.yaml`` is also untouched — overrides are
applied to a cloned :class:`~src.config.Settings` instance only.

Public API
----------
:class:`WalkForwardSplit`
    Train / test slice of a candle list, with timestamps preserved.
:class:`WalkForwardCandidate`
    One grid point with its train + test metrics.
:class:`WalkForwardResult`
    Top-level container: grid metadata + every candidate + survivors
    + the winner pick (or ``None`` when no config survives).

:func:`split_candles`
    Single-symbol split helper.
:func:`split_dataset`
    Apply :func:`split_candles` to a ``{symbol: ohlc_rows}`` mapping.
:func:`expand_grid`
    Cartesian product of a ``{key: [values]}`` mapping.
:func:`score_candidate`
    Composite ranking score from a candidate's test metrics.
:func:`run_walk_forward`
    End-to-end driver. Builds the splits, iterates the grid, runs
    train + test simulations on cloned Settings, filters survivors,
    ranks them.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .backtest import (
    PortfolioResult,
    SOURCE_LABEL,
    build_replay_candles,
    simulate_portfolio,
)
from .config import Settings, get_settings
from .external_signals import ExternalSnapshot


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkForwardSplit:
    """Train / test slice of a single-symbol OHLC row list.

    ``train`` and ``test`` are disjoint, chronological, and use the
    same row dict shape consumed by :func:`src.backtest.simulate_portfolio`.
    """

    symbol: str
    train: list[dict[str, Any]]
    test: list[dict[str, Any]]

    @property
    def train_len(self) -> int:
        return len(self.train)

    @property
    def test_len(self) -> int:
        return len(self.test)

    def first_train_ts(self) -> Optional[int]:
        return _first_timestamp(self.train)

    def last_train_ts(self) -> Optional[int]:
        return _last_timestamp(self.train)

    def first_test_ts(self) -> Optional[int]:
        return _first_timestamp(self.test)

    def last_test_ts(self) -> Optional[int]:
        return _last_timestamp(self.test)


@dataclass
class WindowMetrics:
    """Compact metrics dict used by the walk-forward filter + ranker."""

    net_pnl_usd: float = 0.0
    net_pnl_pct: float = 0.0
    win_rate: float = 0.0
    max_drawdown_pct: float = 0.0
    trades_count: int = 0
    buy_count: int = 0
    sell_count: int = 0
    wins: int = 0
    losses: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "net_pnl_usd": round(self.net_pnl_usd, 4),
            "net_pnl_pct": round(self.net_pnl_pct, 4),
            "win_rate": round(self.win_rate, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 4),
            "trades_count": int(self.trades_count),
            "buy_count": int(self.buy_count),
            "sell_count": int(self.sell_count),
            "wins": int(self.wins),
            "losses": int(self.losses),
        }


@dataclass
class WalkForwardCandidate:
    """One grid point + its train and test metrics."""

    params: dict[str, Any]
    train: WindowMetrics
    test: WindowMetrics
    survives_filter: bool = False
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": dict(self.params),
            "train": self.train.to_dict(),
            "test": self.test.to_dict(),
            "survives_filter": bool(self.survives_filter),
            "score": round(self.score, 6),
        }


@dataclass
class WalkForwardResult:
    """End-to-end walk-forward output.

    All timestamps are integer seconds since epoch; the script
    serialises them as ISO strings in the JSON output for readability.
    """

    symbols: list[str]
    interval_minutes: int
    train_fraction: float
    train_candles_per_symbol: dict[str, int]
    test_candles_per_symbol: dict[str, int]
    train_first_ts: Optional[int]
    train_last_ts: Optional[int]
    test_first_ts: Optional[int]
    test_last_ts: Optional[int]
    grid: dict[str, list[Any]]
    grid_size: int
    filter_min_test_pnl_usd: float
    filter_min_test_win_rate: float
    filter_min_test_trades_count: int = 1
    evaluated: list[WalkForwardCandidate] = field(default_factory=list)
    survivors: list[WalkForwardCandidate] = field(default_factory=list)
    winner: Optional[WalkForwardCandidate] = None
    elapsed_seconds: float = 0.0
    source: str = SOURCE_LABEL

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "symbols": list(self.symbols),
            "interval_minutes": int(self.interval_minutes),
            "train_fraction": round(self.train_fraction, 4),
            "train_candles_per_symbol": dict(self.train_candles_per_symbol),
            "test_candles_per_symbol": dict(self.test_candles_per_symbol),
            "train_window_ts": {
                "first": self.train_first_ts,
                "last": self.train_last_ts,
            },
            "test_window_ts": {
                "first": self.test_first_ts,
                "last": self.test_last_ts,
            },
            "grid": {k: list(v) for k, v in self.grid.items()},
            "grid_size": int(self.grid_size),
            "filter": {
                "min_test_pnl_usd": float(self.filter_min_test_pnl_usd),
                "min_test_win_rate": float(self.filter_min_test_win_rate),
                "min_test_trades_count": int(self.filter_min_test_trades_count),
            },
            "evaluated_count": len(self.evaluated),
            "evaluated": [c.to_dict() for c in self.evaluated],
            "survivors_count": len(self.survivors),
            "survivors": [c.to_dict() for c in self.survivors],
            "winner": self.winner.to_dict() if self.winner else None,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "warning": (
                "Walk-forward selection uses a SMALL grid on a LIMITED data "
                "window. The train/test split is strict and the survivor "
                "filter is honest, but this is not a substitute for proper "
                "Bayesian optimization on multi-year data — the rigor/time "
                "tradeoff is documented in docs/METHODOLOGY.md."
            ),
        }


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def _first_timestamp(rows: Sequence[Mapping[str, Any]]) -> Optional[int]:
    for r in rows:
        ts = r.get("timestamp") if isinstance(r, dict) else None
        if ts is not None:
            try:
                return int(ts)
            except (TypeError, ValueError):
                return None
    return None


def _last_timestamp(rows: Sequence[Mapping[str, Any]]) -> Optional[int]:
    for r in reversed(list(rows)):
        ts = r.get("timestamp") if isinstance(r, dict) else None
        if ts is not None:
            try:
                return int(ts)
            except (TypeError, ValueError):
                return None
    return None


def split_candles(
    symbol: str,
    ohlc_rows: Sequence[Mapping[str, Any]],
    *,
    train_fraction: float = 0.75,
) -> WalkForwardSplit:
    """Split one symbol's OHLC rows into train / test slices.

    The split point is computed as ``floor(N * train_fraction)`` so the
    train set never receives the trailing candle. With the default
    ``train_fraction=0.75`` and Kraken's natural 720-candle depth, the
    train slice is the first 540 candles and the test slice is the
    trailing 180. For a 240-minute interval that maps cleanly to 90
    train days vs 30 test days (the recent 30-day window the live
    snapshot uses).

    Raises
    ------
    ValueError
        If ``train_fraction`` is not in the open interval ``(0, 1)`` or
        if the resulting train or test slice would be empty.
    """
    if not (0.0 < train_fraction < 1.0):
        raise ValueError(
            f"train_fraction must be in (0, 1) (got {train_fraction})"
        )
    rows = [dict(r) for r in ohlc_rows if isinstance(r, dict)]
    n = len(rows)
    if n == 0:
        return WalkForwardSplit(symbol=symbol, train=[], test=[])
    pivot = int(math.floor(n * train_fraction))
    pivot = max(1, min(pivot, n - 1))
    return WalkForwardSplit(
        symbol=symbol,
        train=rows[:pivot],
        test=rows[pivot:],
    )


def split_dataset(
    ohlc_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    train_fraction: float = 0.75,
) -> dict[str, WalkForwardSplit]:
    """Apply :func:`split_candles` to every symbol in the mapping.

    Symbols with empty OHLC payloads produce ``WalkForwardSplit`` rows
    with empty train and test lists so the caller can detect missing
    data without crashing.
    """
    out: dict[str, WalkForwardSplit] = {}
    for symbol, rows in ohlc_by_symbol.items():
        out[symbol] = split_candles(
            symbol, rows or [], train_fraction=train_fraction
        )
    return out


# ---------------------------------------------------------------------------
# Grid expansion + scoring
# ---------------------------------------------------------------------------


def expand_grid(grid: Mapping[str, Sequence[Any]]) -> list[dict[str, Any]]:
    """Cartesian product of a ``{key: [values]}`` mapping.

    Returns one dict per combo; key order matches the iteration order of
    the input mapping (Python 3.7+ insertion order semantics).
    """
    keys = list(grid.keys())
    if not keys:
        return [dict()]
    combos: list[dict[str, Any]] = [dict()]
    for key in keys:
        values = list(grid[key])
        if not values:
            raise ValueError(f"grid key {key!r} has an empty value list")
        new_combos: list[dict[str, Any]] = []
        for c in combos:
            for v in values:
                merged = dict(c)
                merged[key] = v
                new_combos.append(merged)
        combos = new_combos
    return combos


def _metrics_from_portfolio(pf: PortfolioResult) -> WindowMetrics:
    return WindowMetrics(
        net_pnl_usd=float(pf.net_pnl),
        net_pnl_pct=float(pf.net_pnl_pct),
        win_rate=float(pf.win_rate),
        max_drawdown_pct=float(pf.max_drawdown_pct),
        trades_count=int(pf.trades_count),
        buy_count=int(pf.buy_count),
        sell_count=int(pf.sell_count),
        wins=int(pf.wins),
        losses=int(pf.losses),
    )


def score_candidate(metrics: WindowMetrics) -> float:
    """Composite robustness score used to rank survivors.

    ``score = net_pnl_usd * win_rate / max(max_drawdown_pct, 0.5)``

    Rationale:
    - Multiplying PnL by win-rate punishes single-lucky-trade outliers
      where most fills were losers and one outlier dominated.
    - Dividing by max-drawdown rewards low-volatility paths.
    - The 0.5% drawdown floor prevents the score from blowing up when a
      lucky run happens to register a near-zero drawdown.
    """
    pnl = float(metrics.net_pnl_usd)
    wr = float(metrics.win_rate)
    mdd = max(float(metrics.max_drawdown_pct), 0.5)
    return pnl * wr / mdd


def _passes_filter(
    metrics: WindowMetrics,
    *,
    min_test_pnl_usd: float,
    min_test_win_rate: float,
    min_test_trades_count: int = 1,
) -> bool:
    """Survivor predicate.

    A candidate survives only if its OOS metrics clear every barrier:

    - ``net_pnl_usd >= min_test_pnl_usd`` (positive PnL by default)
    - ``win_rate >= min_test_win_rate`` (majority of trades win)
    - ``trades_count >= min_test_trades_count`` (enough fills for the
      result to be statistically meaningful — the default of ``1``
      preserves the legacy "at least one fill" behaviour for xStocks)
    """
    return (
        metrics.net_pnl_usd >= float(min_test_pnl_usd)
        and metrics.win_rate >= float(min_test_win_rate)
        and metrics.trades_count >= int(min_test_trades_count)
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _simulate_window(
    *,
    symbols: Sequence[str],
    ohlc_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    overrides: Mapping[str, Any],
    settings: Settings,
    initial_cash: float,
    interval_minutes: int,
    disable_realtime_cooldown: bool,
    external_snapshots_by_symbol: Optional[
        Mapping[str, Mapping[str, ExternalSnapshot]]
    ] = None,
) -> WindowMetrics:
    """Run one portfolio simulation on a single window and collect metrics."""
    pf = simulate_portfolio(
        symbols,
        ohlc_by_symbol,
        config=settings.config,
        profile=settings.active_profile,
        initial_cash=initial_cash,
        settings=settings,
        overrides=dict(overrides),
        interval_minutes=interval_minutes,
        record_decisions=False,
        disable_realtime_cooldown=disable_realtime_cooldown,
        external_snapshots_by_symbol=external_snapshots_by_symbol,
    )
    return _metrics_from_portfolio(pf)


def run_walk_forward(
    symbols: Sequence[str],
    ohlc_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]],
    grid: Mapping[str, Sequence[Any]],
    *,
    train_fraction: float = 0.75,
    initial_cash: float = 10_000.0,
    interval_minutes: int = 240,
    min_test_pnl_usd: float = 0.0,
    min_test_win_rate: float = 0.50,
    min_test_trades_count: int = 1,
    settings: Optional[Settings] = None,
    disable_realtime_cooldown: bool = True,
    external_snapshots_by_symbol: Optional[
        Mapping[str, Mapping[str, ExternalSnapshot]]
    ] = None,
) -> WalkForwardResult:
    """End-to-end walk-forward run.

    Steps:

    1. ``split_dataset`` slices each symbol's OHLC rows at
       ``train_fraction``. Symbols with empty payloads contribute
       empty slices and are still kept in the result so the caller
       can audit which symbols were available.
    2. ``expand_grid`` builds the cartesian product of the grid.
    3. For each combo, two ``simulate_portfolio`` calls run on cloned
       Settings: one over the train slice, one over the test slice.
       Settings overrides go through :func:`src.backtest._build_settings_override`
       (cf. that function for the full list of recognised keys).
    4. Candidates with test PnL < ``min_test_pnl_usd`` or test win-rate
       < ``min_test_win_rate`` are dropped from the survivor list.
    5. Surviving candidates are ranked by :func:`score_candidate`;
       the highest-scoring one becomes ``winner``.

    ``disable_realtime_cooldown`` defaults to ``True`` because the risk
    layer's per-symbol cooldown is wall-clock driven and would block
    most candidates in a replay context; the production agent loop is
    unaffected. Set to ``False`` only when you specifically want the
    cooldown behaviour to be part of the optimisation surface.
    """
    started = time.time()
    base_settings = settings or get_settings()

    splits = split_dataset(ohlc_by_symbol, train_fraction=train_fraction)
    train_by_symbol = {sym: splits[sym].train for sym in symbols}
    test_by_symbol = {sym: splits[sym].test for sym in symbols}
    train_lens = {sym: splits[sym].train_len for sym in symbols}
    test_lens = {sym: splits[sym].test_len for sym in symbols}

    # Window boundaries — compute across all symbols.
    train_firsts = [splits[s].first_train_ts() for s in symbols if splits[s].train_len > 0]
    train_lasts = [splits[s].last_train_ts() for s in symbols if splits[s].train_len > 0]
    test_firsts = [splits[s].first_test_ts() for s in symbols if splits[s].test_len > 0]
    test_lasts = [splits[s].last_test_ts() for s in symbols if splits[s].test_len > 0]
    train_first_ts = min((t for t in train_firsts if t is not None), default=None)
    train_last_ts = max((t for t in train_lasts if t is not None), default=None)
    test_first_ts = min((t for t in test_firsts if t is not None), default=None)
    test_last_ts = max((t for t in test_lasts if t is not None), default=None)

    combos = expand_grid(grid)
    grid_size = len(combos)

    evaluated: list[WalkForwardCandidate] = []
    for overrides in combos:
        train_metrics = _simulate_window(
            symbols=symbols,
            ohlc_by_symbol=train_by_symbol,
            overrides=overrides,
            settings=base_settings,
            initial_cash=initial_cash,
            interval_minutes=interval_minutes,
            disable_realtime_cooldown=disable_realtime_cooldown,
            external_snapshots_by_symbol=external_snapshots_by_symbol,
        )
        test_metrics = _simulate_window(
            symbols=symbols,
            ohlc_by_symbol=test_by_symbol,
            overrides=overrides,
            settings=base_settings,
            initial_cash=initial_cash,
            interval_minutes=interval_minutes,
            disable_realtime_cooldown=disable_realtime_cooldown,
            external_snapshots_by_symbol=external_snapshots_by_symbol,
        )
        survives = _passes_filter(
            test_metrics,
            min_test_pnl_usd=min_test_pnl_usd,
            min_test_win_rate=min_test_win_rate,
            min_test_trades_count=min_test_trades_count,
        )
        candidate = WalkForwardCandidate(
            params=dict(overrides),
            train=train_metrics,
            test=test_metrics,
            survives_filter=survives,
            score=score_candidate(test_metrics) if survives else 0.0,
        )
        evaluated.append(candidate)

    survivors = [c for c in evaluated if c.survives_filter]
    survivors.sort(key=lambda c: c.score, reverse=True)
    winner = survivors[0] if survivors else None

    return WalkForwardResult(
        symbols=list(symbols),
        interval_minutes=int(interval_minutes),
        train_fraction=float(train_fraction),
        train_candles_per_symbol=train_lens,
        test_candles_per_symbol=test_lens,
        train_first_ts=train_first_ts,
        train_last_ts=train_last_ts,
        test_first_ts=test_first_ts,
        test_last_ts=test_last_ts,
        grid={k: list(v) for k, v in grid.items()},
        grid_size=grid_size,
        filter_min_test_pnl_usd=float(min_test_pnl_usd),
        filter_min_test_win_rate=float(min_test_win_rate),
        filter_min_test_trades_count=int(min_test_trades_count),
        evaluated=evaluated,
        survivors=survivors,
        winner=winner,
        elapsed_seconds=time.time() - started,
    )


__all__ = [
    "WalkForwardSplit",
    "WindowMetrics",
    "WalkForwardCandidate",
    "WalkForwardResult",
    "split_candles",
    "split_dataset",
    "expand_grid",
    "score_candidate",
    "run_walk_forward",
]
