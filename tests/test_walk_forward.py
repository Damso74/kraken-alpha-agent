"""Walk-forward optimization regression tests.

Invariants under test:
- ``split_candles`` returns disjoint, chronologically sorted train and
  test slices whose sizes match ``floor(N * train_fraction)``.
- ``split_candles`` raises ``ValueError`` for an out-of-range fraction.
- ``expand_grid`` returns the full cartesian product and raises on
  empty value lists.
- ``score_candidate`` clamps small drawdowns to the 0.5% floor so a
  near-zero drawdown does not inflate the score to infinity.
- ``run_walk_forward`` reuses an injected :class:`Settings` instance,
  filters out candidates that fail the survivor check, and never
  surfaces a winner when no candidate survives.

The driver test uses synthetic dict-shaped OHLC rows so the suite
remains hermetic (no Kraken CLI shell-out, no `.env` dependency).
"""

from __future__ import annotations

import pytest

from src.config import get_settings
from src.walk_forward import (
    WalkForwardCandidate,
    WindowMetrics,
    expand_grid,
    run_walk_forward,
    score_candidate,
    split_candles,
    split_dataset,
)


# ---------------------------------------------------------------------------
# Synthetic OHLC fixtures
# ---------------------------------------------------------------------------


def _flat_candles(symbol: str, count: int, start_ts: int = 1_700_000_000) -> list[dict]:
    """Generate a synthetic, dict-shaped OHLC payload.

    The price wobbles slightly so the engine has *some* signal to chew
    on, but the dataset is intentionally non-trending so very few BUYs
    fire — the goal here is to exercise the walk-forward plumbing,
    not to validate the strategy's PnL.
    """
    rows: list[dict] = []
    price = 100.0
    for i in range(count):
        price += 0.05 if i % 2 == 0 else -0.04
        rows.append(
            {
                "timestamp": start_ts + i * 240 * 60,
                "open": round(price, 4),
                "high": round(price * 1.001, 4),
                "low": round(price * 0.999, 4),
                "close": round(price, 4),
                "vwap": round(price, 4),
                "volume": 5_000.0,
            }
        )
    return rows


# ---------------------------------------------------------------------------
# split_candles / split_dataset
# ---------------------------------------------------------------------------


def test_split_candles_default_fraction_is_75_25() -> None:
    rows = _flat_candles("NVDAx", count=720)
    sp = split_candles("NVDAx", rows, train_fraction=0.75)
    # floor(720 * 0.75) = 540
    assert sp.train_len == 540
    assert sp.test_len == 180
    # Slices are disjoint and chronological.
    assert sp.train[-1]["timestamp"] < sp.test[0]["timestamp"]


def test_split_candles_custom_fraction() -> None:
    rows = _flat_candles("NVDAx", count=100)
    sp = split_candles("NVDAx", rows, train_fraction=0.5)
    assert sp.train_len == 50
    assert sp.test_len == 50
    assert sp.train_len + sp.test_len == len(rows)


def test_split_candles_clamps_extreme_fraction() -> None:
    rows = _flat_candles("NVDAx", count=10)
    sp_low = split_candles("NVDAx", rows, train_fraction=0.01)
    # floor(10 * 0.01) = 0 → clamped to 1 so test still has data.
    assert sp_low.train_len == 1
    assert sp_low.test_len == 9
    sp_high = split_candles("NVDAx", rows, train_fraction=0.99)
    # floor(10 * 0.99) = 9 → bounded so test slice retains 1 candle.
    assert sp_high.train_len == 9
    assert sp_high.test_len == 1


def test_split_candles_rejects_invalid_fraction() -> None:
    rows = _flat_candles("NVDAx", count=10)
    with pytest.raises(ValueError):
        split_candles("NVDAx", rows, train_fraction=0.0)
    with pytest.raises(ValueError):
        split_candles("NVDAx", rows, train_fraction=1.0)
    with pytest.raises(ValueError):
        split_candles("NVDAx", rows, train_fraction=-0.1)


def test_split_dataset_preserves_symbol_order() -> None:
    payload = {
        "NVDAx": _flat_candles("NVDAx", 100),
        "AAPLx": _flat_candles("AAPLx", 60),
        "EMPTYx": [],
    }
    splits = split_dataset(payload, train_fraction=0.8)
    assert set(splits.keys()) == {"NVDAx", "AAPLx", "EMPTYx"}
    assert splits["NVDAx"].train_len == 80
    assert splits["NVDAx"].test_len == 20
    assert splits["AAPLx"].train_len == 48
    assert splits["AAPLx"].test_len == 12
    # Empty payload survives without crashing.
    assert splits["EMPTYx"].train == []
    assert splits["EMPTYx"].test == []


# ---------------------------------------------------------------------------
# expand_grid
# ---------------------------------------------------------------------------


def test_expand_grid_cartesian_product() -> None:
    combos = expand_grid({"a": [1, 2], "b": [10, 20, 30]})
    assert len(combos) == 6
    # Every combo carries every key.
    assert all(set(c.keys()) == {"a", "b"} for c in combos)
    # Every (a, b) pair appears exactly once.
    pairs = {(c["a"], c["b"]) for c in combos}
    assert pairs == {(1, 10), (1, 20), (1, 30), (2, 10), (2, 20), (2, 30)}


def test_expand_grid_rejects_empty_value_list() -> None:
    with pytest.raises(ValueError):
        expand_grid({"a": [], "b": [1]})


def test_expand_grid_empty_input_returns_single_empty_combo() -> None:
    # Edge case: an empty grid is treated as "no overrides".
    combos = expand_grid({})
    assert combos == [{}]


# ---------------------------------------------------------------------------
# score_candidate
# ---------------------------------------------------------------------------


def test_score_candidate_handles_zero_drawdown() -> None:
    metrics = WindowMetrics(
        net_pnl_usd=100.0,
        net_pnl_pct=1.0,
        win_rate=0.6,
        max_drawdown_pct=0.0,  # would divide by zero without the floor
        trades_count=10,
        wins=6,
        losses=4,
    )
    score = score_candidate(metrics)
    # max(0.0, 0.5) = 0.5 → 100 * 0.6 / 0.5 = 120.0
    assert score == pytest.approx(120.0)


def test_score_candidate_rewards_higher_win_rate() -> None:
    base = WindowMetrics(net_pnl_usd=50.0, win_rate=0.50, max_drawdown_pct=1.0, trades_count=10)
    better = WindowMetrics(net_pnl_usd=50.0, win_rate=0.70, max_drawdown_pct=1.0, trades_count=10)
    assert score_candidate(better) > score_candidate(base)


def test_score_candidate_penalises_higher_drawdown() -> None:
    base = WindowMetrics(net_pnl_usd=50.0, win_rate=0.60, max_drawdown_pct=1.0, trades_count=10)
    worse = WindowMetrics(net_pnl_usd=50.0, win_rate=0.60, max_drawdown_pct=4.0, trades_count=10)
    assert score_candidate(worse) < score_candidate(base)


# ---------------------------------------------------------------------------
# run_walk_forward
# ---------------------------------------------------------------------------


def test_run_walk_forward_no_survivors_returns_no_winner() -> None:
    """Force every candidate to fail the filter so we get winner=None.

    The synthetic flat dataset rarely triggers BUY signals — combined
    with a high minimum-win-rate filter, no combo passes.
    """
    settings = get_settings()
    symbols = ["NVDAx", "AAPLx"]
    ohlc = {sym: _flat_candles(sym, 120) for sym in symbols}
    # Tiny grid keeps the test fast.
    grid = {
        "min_confidence_to_trade": [0.10, 0.30],
        "min_opportunity_score_buy": [0.04, 0.08],
    }
    result = run_walk_forward(
        symbols=symbols,
        ohlc_by_symbol=ohlc,
        grid=grid,
        train_fraction=0.75,
        initial_cash=10_000.0,
        interval_minutes=240,
        min_test_pnl_usd=10_000.0,  # impossibly high → no survivors
        min_test_win_rate=0.99,
        settings=settings,
    )
    assert result.grid_size == 4
    assert len(result.evaluated) == 4
    assert result.survivors == []
    assert result.winner is None
    # Train / test split metadata is populated.
    assert result.train_candles_per_symbol == {"NVDAx": 90, "AAPLx": 90}
    assert result.test_candles_per_symbol == {"NVDAx": 30, "AAPLx": 30}
    # Every evaluated candidate carries both train and test metrics.
    for cand in result.evaluated:
        assert isinstance(cand, WalkForwardCandidate)
        assert cand.train.trades_count >= 0
        assert cand.test.trades_count >= 0
        assert cand.score == 0.0  # survivors-only ranking


def test_run_walk_forward_survivor_ranking_is_descending() -> None:
    """When at least one candidate survives, the winner has the top score."""
    settings = get_settings()
    symbols = ["NVDAx"]
    ohlc = {"NVDAx": _flat_candles("NVDAx", 120)}
    grid = {
        "min_opportunity_score_buy": [0.04],
        "min_confidence_to_trade": [0.10],
    }
    # Filter relaxed so any zero-trade candidate still falls out (the
    # filter also requires trades_count > 0 — see _passes_filter), but
    # if any trade fires we keep the winner check sane.
    result = run_walk_forward(
        symbols=symbols,
        ohlc_by_symbol=ohlc,
        grid=grid,
        train_fraction=0.75,
        initial_cash=10_000.0,
        interval_minutes=240,
        min_test_pnl_usd=-1_000.0,
        min_test_win_rate=0.0,
        settings=settings,
    )
    # Either no trades fired (survivor list empty) OR the winner is the
    # top-scoring survivor — both are valid outcomes for synthetic data.
    if result.survivors:
        scores = [c.score for c in result.survivors]
        assert scores == sorted(scores, reverse=True)
        assert result.winner is result.survivors[0]
    else:
        assert result.winner is None
