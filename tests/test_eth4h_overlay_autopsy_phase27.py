"""Phase 27D — ETH 4h overlay autopsy (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.bot.basis_crowding_overlay import classify_eth_overlay_autopsy_verdict
from src.bot.journal import BotJournal
from src.bot.phase27_eth4h_autopsy import (
    ETH4H_AUTOPSY_TARGETS,
    _time_in_market_pct,
    run_eth4h_autopsy_cell,
)


def _candles(n: int, step: int = 14400) -> list[dict]:
    t0 = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    return [
        {
            "timestamp": t0 + i * step,
            "open": 100.0 + i * 0.2,
            "high": 102.0 + i * 0.2,
            "low": 98.0 + i * 0.2,
            "close": 101.0 + i * 0.2,
            "volume": 10.0,
        }
        for i in range(n)
    ]


def _deriv_rows(candles: list, *, n_fund: float = 0.0001, oi: float = 1000.0) -> tuple[list, list]:
    fund = [
        {"timestamp": int(c["timestamp"]), "funding_rate": n_fund}
        for c in candles[::4]
    ]
    oi_rows = [
        {"timestamp": int(c["timestamp"]), "open_interest": oi + i}
        for i, c in enumerate(candles[::4])
    ]
    return fund, oi_rows


def test_eth4h_autopsy_targets_count() -> None:
    assert len(ETH4H_AUTOPSY_TARGETS) == 3


def test_classify_useful_overlay() -> None:
    v = classify_eth_overlay_autopsy_verdict(
        {"data_ok": True, "total_return_pct": 5, "max_drawdown_pct": 20},
        {"data_ok": True, "total_return_pct": 4, "max_drawdown_pct": 12},
        missed_upside_pct=2.0,
    )
    assert v == "useful_overlay"


def test_classify_kill_overlay() -> None:
    v = classify_eth_overlay_autopsy_verdict(
        {"data_ok": True, "total_return_pct": 10, "max_drawdown_pct": 15},
        {"data_ok": True, "total_return_pct": 2, "max_drawdown_pct": 16},
        missed_upside_pct=15.0,
    )
    assert v == "kill_overlay"


def test_run_eth4h_autopsy_cell_smoke() -> None:
    candles = _candles(400)
    fund, oi = _deriv_rows(candles)
    row = run_eth4h_autopsy_cell(
        "ema_crossover",
        "baseline",
        candles,
        f_rows=fund,
        o_rows=oi,
        fee_bps=10.0,
    )
    assert row["verdict"] in ("useful_overlay", "decorative", "kill_overlay")
    assert "fee_sensitivity" in row
    assert len(row["fee_sensitivity"]) == 4
    assert "period_stability" in row


def _journal_with(pairs: list[tuple[int, int]]) -> BotJournal:
    """Journal whose trades open at ``buy_bar`` and close at ``sell_bar``."""
    j = BotJournal()
    for buy_bar, sell_bar in pairs:
        j.trades.append({"side": "buy", "bar_index": buy_bar})
        j.trades.append({"side": "sell", "bar_index": sell_bar})
    return j


def test_time_in_market_pct_half_of_usable_bars_is_fifty() -> None:
    # 100 bars, warmup 0 -> 100 usable bars ; position held on bars 0..50.
    j = _journal_with([(0, 50)])
    assert _time_in_market_pct(j, 100, warmup=0) == 50.0


def test_time_in_market_pct_half_with_warmup() -> None:
    # 120 bars, warmup 20 -> 100 usable bars ; held 50 of them.
    j = _journal_with([(20, 70)])
    assert _time_in_market_pct(j, 120, warmup=20) == 50.0


def test_time_in_market_pct_scale_is_percent_not_fraction_nor_permille() -> None:
    j = _journal_with([(0, 50)])
    v = _time_in_market_pct(j, 100, warmup=0)
    assert 45.0 <= v <= 55.0
    assert v > 1.5  # not a raw 0..1 fraction (~0.5)
    assert v <= 100.0  # not the old x10 blow-up (~500)


def test_time_in_market_pct_full_exposure_is_near_hundred() -> None:
    j = BotJournal()
    j.trades.append({"side": "buy", "bar_index": 0})  # still open at the end
    # The reference metric counts bar spans (last bar index = total_bars - 1),
    # so a position open on every bar scores 99, never above 100.
    assert _time_in_market_pct(j, 100, warmup=0) == 99.0


def test_time_in_market_pct_empty_journal_is_zero() -> None:
    assert _time_in_market_pct(BotJournal(), 100, warmup=0) == 0.0


def test_time_in_market_pct_is_not_a_buy_count_proxy() -> None:
    """Many short round-trips must not inflate the metric above real exposure."""
    # 10 round-trips of 1 bar each over 100 usable bars -> 10 %, not 1000 %.
    j = _journal_with([(i * 10, i * 10 + 1) for i in range(10)])
    assert _time_in_market_pct(j, 100, warmup=0) == 10.0


def test_run_eth4h_autopsy_cell_time_in_market_is_percent_scale() -> None:
    candles = _candles(400)
    fund, oi = _deriv_rows(candles)
    row = run_eth4h_autopsy_cell(
        "ema_crossover",
        "baseline",
        candles,
        f_rows=fund,
        o_rows=oi,
        fee_bps=10.0,
    )
    for block in ("baseline", "overlay"):
        tim = row[block]["time_in_market_pct"]
        assert 0.0 <= tim <= 100.0
