"""Phase 26B — derivatives event study (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.bot.derivatives_event_study import (
    classify_event_study_verdict,
    run_all_derivatives_event_studies,
    run_signal_event_study,
)
from src.data.collectors.binance_derivatives_public import save_funding_cache, save_oi_cache


def _candles(n: int, step: int = 14400) -> list[dict]:
    t0 = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp())
    out = []
    price = 100.0
    for i in range(n):
        price += 0.05 if i % 7 else -0.02
        out.append(
            {
                "timestamp": t0 + i * step,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 10.0,
            }
        )
    return out


def _seed_derivatives(tmp_path: Path) -> None:
    fund_rows = [
        {"fundingTime": 1_640_000_000 + i * 28800, "fundingRate": f"{0.0001 * (i % 20 - 10)}"}
        for i in range(200)
    ]
    save_funding_cache(tmp_path / "funding_BTC.json", ticker="BTC", rows=fund_rows)
    oi_rows = [
        {"timestamp": 1_640_000_000 + i * 14400, "sumOpenInterest": str(1000 + i * 5)}
        for i in range(200)
    ]
    save_oi_cache(tmp_path / "oi_BTC_4h.json", ticker="BTC", period="4h", rows=oi_rows)


def test_liquidation_signal_blocked() -> None:
    candles = _candles(200)
    r = run_signal_event_study("liquidation_spike", candles, [], [])
    assert r.status == "blocked_data"


def test_funding_event_study_with_cache(tmp_path: Path) -> None:
    _seed_derivatives(tmp_path)
    candles = _candles(250)
    bundle = run_all_derivatives_event_studies(
        "BTC", candles, timeframe="4h", cache_root=tmp_path
    )
    assert bundle["funding_rows"] >= 100
    assert bundle["oi_rows"] >= 100
    assert any(s["signal_id"] == "funding_extreme" for s in bundle["results"])


def test_classify_verdict_blocked() -> None:
    assert classify_event_study_verdict({"funding_rows": 0, "oi_rows": 0}) == "blocked_data"
