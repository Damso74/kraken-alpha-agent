"""Phase 27D — ETH 4h overlay autopsy (no network)."""

from __future__ import annotations

from datetime import datetime, timezone

from src.bot.basis_crowding_overlay import classify_eth_overlay_autopsy_verdict
from src.bot.phase27_eth4h_autopsy import (
    ETH4H_AUTOPSY_TARGETS,
    run_eth4h_autopsy_cell,
)


def _candles(n: int, step: int = 14400) -> list[dict]:
    t0 = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp())
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
