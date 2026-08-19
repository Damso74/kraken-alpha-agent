"""Regression tests for the external-signals module.

The module is split into three independent helpers and we cover each
through hermetic tests (no live HTTP, no live filesystem outside of
``tmp_path``):

- Fear & Greed: cache hit/miss, malformed payload, range filtering.
- BTC dominance: /global parsing, top-10 reconstruction, cache merging
  with the documented "current-only" caveat.
- Realized vol regime: low / normal / high classification on hand-built
  OHLC sequences.

Where the production code accepts injectable fetchers, the tests pass
in a closure so the network layer is never exercised.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from src.external_signals import (
    ExternalSignalError,
    compute_btc_dominance_from_markets,
    compute_realized_vol_regime,
    fetch_btc_dominance,
    fetch_fear_greed,
    parse_btc_dominance_global,
    parse_fear_greed_payload,
    pick_for_date,
)

# ---------------------------------------------------------------------------
# Fear & Greed
# ---------------------------------------------------------------------------


def _fng_row(value: int, day: date) -> dict:
    """Build one row of the alternative.me Fear & Greed payload."""
    ts = int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())
    return {"value": str(int(value)), "timestamp": str(ts), "value_classification": "Neutral"}


def test_parse_fear_greed_payload_filters_malformed_rows() -> None:
    payload = {
        "data": [
            _fng_row(50, date(2026, 5, 17)),
            {"value": "not-a-number", "timestamp": "1700000000"},  # malformed
            _fng_row(72, date(2026, 5, 18)),
            {},  # empty
            _fng_row(150, date(2026, 5, 19)),  # over-clamped value
        ],
    }
    parsed = parse_fear_greed_payload(payload)
    assert parsed[date(2026, 5, 17)] == 50
    assert parsed[date(2026, 5, 18)] == 72
    assert parsed[date(2026, 5, 19)] == 100  # clamped
    assert len(parsed) == 3


def test_fetch_fear_greed_cache_hit_skips_fetcher(tmp_path: Path) -> None:
    cache_path = tmp_path / "fng_cache.json"
    cache_path.write_text(
        json.dumps(
            {
                "source": "alternative_me_fng",
                "entries": {
                    "2026-05-17": 50,
                    "2026-05-18": 72,
                    "2026-05-19": 65,
                },
            }
        ),
        encoding="utf-8",
    )

    def explode(_limit: int) -> dict:
        raise AssertionError("fetcher must not be called on a cache hit")

    series = fetch_fear_greed(
        "2026-05-17",
        "2026-05-19",
        cache_path=cache_path,
        fetcher=explode,
    )
    assert series == {
        date(2026, 5, 17): 50,
        date(2026, 5, 18): 72,
        date(2026, 5, 19): 65,
    }


def test_fetch_fear_greed_cache_miss_calls_fetcher_and_persists(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "fng_cache.json"
    payload = {
        "data": [
            _fng_row(40, date(2026, 5, 17)),
            _fng_row(44, date(2026, 5, 18)),
            _fng_row(60, date(2026, 5, 19)),
        ]
    }
    calls = {"n": 0}

    def fake_fetcher(_limit: int) -> dict:
        calls["n"] += 1
        return payload

    series = fetch_fear_greed(
        "2026-05-17",
        "2026-05-19",
        cache_path=cache_path,
        fetcher=fake_fetcher,
    )
    assert calls["n"] == 1
    assert series[date(2026, 5, 17)] == 40
    assert series[date(2026, 5, 19)] == 60
    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert "2026-05-17" in persisted["entries"]


def test_fetch_fear_greed_invalid_window_raises() -> None:
    with pytest.raises(ValueError):
        fetch_fear_greed("not-a-date", "2026-05-18", cache_path=None)
    with pytest.raises(ValueError):
        fetch_fear_greed("2026-05-19", "2026-05-17", cache_path=None)


# ---------------------------------------------------------------------------
# BTC dominance
# ---------------------------------------------------------------------------


def test_parse_btc_dominance_global_extracts_pct() -> None:
    payload = {
        "data": {
            "active_cryptocurrencies": 12_345,
            "market_cap_percentage": {"btc": 51.42, "eth": 16.10},
        }
    }
    assert parse_btc_dominance_global(payload) == pytest.approx(51.42)
    assert parse_btc_dominance_global({}) is None
    assert parse_btc_dominance_global({"data": {}}) is None
    assert parse_btc_dominance_global({"data": {"market_cap_percentage": {}}}) is None


def test_compute_btc_dominance_from_markets_handles_top10() -> None:
    markets = [
        {"id": "bitcoin", "symbol": "btc", "market_cap": 1_300_000_000_000.0},
        {"id": "ethereum", "symbol": "eth", "market_cap": 400_000_000_000.0},
        {"id": "solana", "symbol": "sol", "market_cap": 100_000_000_000.0},
        {"id": "ripple", "symbol": "xrp", "market_cap": 50_000_000_000.0},
        {"id": "cardano", "symbol": "ada", "market_cap": 30_000_000_000.0},
    ]
    dom = compute_btc_dominance_from_markets(markets)
    assert dom is not None
    # 1 300 / 1 880 ≈ 69.15 %
    assert dom == pytest.approx(69.148936, abs=1e-3)


def test_compute_btc_dominance_from_markets_returns_none_without_btc() -> None:
    markets = [{"id": "ethereum", "symbol": "eth", "market_cap": 100.0}]
    assert compute_btc_dominance_from_markets(markets) is None


def test_fetch_btc_dominance_uses_global_and_persists_cache(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "btc_dom.json"
    today = datetime.now(UTC).date()
    yesterday = today - timedelta(days=1)

    def global_fetcher() -> dict:
        return {"data": {"market_cap_percentage": {"btc": 53.1}}}

    series = fetch_btc_dominance(
        yesterday.isoformat(),
        today.isoformat(),
        cache_path=cache_path,
        global_fetcher=global_fetcher,
    )
    assert series[today] == pytest.approx(53.1)
    persisted = json.loads(cache_path.read_text(encoding="utf-8"))
    assert today.isoformat() in persisted["entries"]
    # Hard caveat surfaced: warning string in the cache.
    assert "warning" in persisted


def test_fetch_btc_dominance_global_failure_falls_back_to_markets(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "btc_dom.json"
    today = datetime.now(UTC).date()

    def global_fetcher() -> dict:
        raise ExternalSignalError("simulated /global failure")

    def markets_fetcher(_per_page: int) -> list:
        return [
            {"id": "bitcoin", "symbol": "btc", "market_cap": 1_000_000.0},
            {"id": "ethereum", "symbol": "eth", "market_cap": 1_000_000.0},
        ]

    series = fetch_btc_dominance(
        today.isoformat(),
        today.isoformat(),
        cache_path=cache_path,
        global_fetcher=global_fetcher,
        markets_fetcher=markets_fetcher,
    )
    # 1M / 2M = 50 %
    assert series[today] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Realized vol regime
# ---------------------------------------------------------------------------


def _make_ohlc(closes: list[float]) -> list[dict]:
    return [
        {
            "timestamp": 1_700_000_000 + i * 3600,
            "open": p,
            "high": p * 1.001,
            "low": p * 0.999,
            "close": p,
            "vwap": p,
            "volume": 5_000.0,
        }
        for i, p in enumerate(closes)
    ]


def test_compute_realized_vol_regime_low_branch() -> None:
    """Last window should land in the low quartile when the tail is calm.

    We build a series where the first half jitters wildly (creating a
    large rolling-stdev population) and the last 21 candles are
    monotonic so the trailing rolling std is near zero.
    """
    noisy = [100.0]
    for i in range(1, 100):
        # Big alternating moves → high stdev across the early window.
        noisy.append(noisy[-1] * (1.05 if i % 2 == 0 else 0.95))
    # 21 calm candles drift up by 0.01 % each step.
    calm = [noisy[-1] * (1 + 0.0001 * i) for i in range(21)]
    breakdown = compute_realized_vol_regime(_make_ohlc(noisy + calm), window=20)
    assert breakdown.label == "low"
    assert breakdown.rolling_std < breakdown.q25
    assert breakdown.sample_size > 50


def test_compute_realized_vol_regime_high_branch() -> None:
    """Last window should land above the q75 threshold on a sudden vol spike."""
    calm = [100.0]
    for i in range(1, 80):
        calm.append(calm[-1] * (1 + 0.0005 * (1 if i % 2 == 0 else -1)))
    spike = [calm[-1]]
    for i in range(1, 41):
        # Last 40 candles whip back and forth by 5 % → very high stdev.
        spike.append(spike[-1] * (1.05 if i % 2 == 0 else 0.95))
    breakdown = compute_realized_vol_regime(_make_ohlc(calm + spike), window=20)
    assert breakdown.label == "high"
    assert breakdown.rolling_std > breakdown.q75


def test_compute_realized_vol_regime_handles_empty_inputs() -> None:
    assert compute_realized_vol_regime([], window=20).label == "normal"
    assert compute_realized_vol_regime(None, window=20).label == "normal"
    # Window larger than the data → returns the safe default.
    assert (
        compute_realized_vol_regime(_make_ohlc([100.0, 101.0]), window=20).label
        == "normal"
    )


# ---------------------------------------------------------------------------
# pick_for_date helper
# ---------------------------------------------------------------------------


def test_pick_for_date_falls_back_to_previous_known_day() -> None:
    series = {date(2026, 5, 1): 10, date(2026, 5, 5): 20, date(2026, 5, 10): 30}
    assert pick_for_date(series, date(2026, 5, 5)) == 20
    assert pick_for_date(series, date(2026, 5, 7)) == 20
    assert pick_for_date(series, date(2026, 5, 11)) == 30
    assert pick_for_date(series, date(2026, 4, 30), fallback=-1) == -1


# ---------------------------------------------------------------------------
# Gate application + actionability integration
# ---------------------------------------------------------------------------


def test_apply_external_gates_blocks_buy_on_extreme_fear() -> None:
    from src.config import ExternalSignalsConfig
    from src.external_signals import ExternalSnapshot, apply_external_gates

    snap = ExternalSnapshot(fear_greed_index=20)
    gates = ExternalSignalsConfig(block_buy_if_fear_greed_lt=25)

    block = apply_external_gates(
        action="BUY", symbol="ETH", snapshot=snap, gates=gates
    )
    assert block is not None
    assert "fear_greed_lt" in block

    # SELL/HOLD bypass the same gate.
    assert apply_external_gates(action="SELL", symbol="ETH", snapshot=snap, gates=gates) is None
    assert apply_external_gates(action="HOLD", symbol="ETH", snapshot=snap, gates=gates) is None


def test_apply_external_gates_btc_dominance_only_blocks_alts() -> None:
    from src.config import ExternalSignalsConfig
    from src.external_signals import ExternalSnapshot, apply_external_gates

    rising = ExternalSnapshot(
        btc_dominance_pct=53.0, btc_dominance_pct_24h_ago=51.5
    )
    gates = ExternalSignalsConfig(block_alt_if_btc_dominance_rising_24h_pct=1.0)

    # Alt symbol blocked (delta = +1.5 pp > +1.0 pp threshold).
    block = apply_external_gates(
        action="BUY", symbol="ETH", snapshot=rising, gates=gates
    )
    assert block is not None
    assert "btc_dominance_rising" in block

    # BTC itself is exempt from the alt-only gate.
    assert apply_external_gates(
        action="BUY", symbol="BTC", snapshot=rising, gates=gates
    ) is None


def test_apply_external_gates_vol_regime_filter() -> None:
    from src.config import ExternalSignalsConfig
    from src.external_signals import ExternalSnapshot, apply_external_gates

    gates = ExternalSignalsConfig(vol_regime_filter=["normal", "high"])

    # "low" is not in the allow-list → block.
    block = apply_external_gates(
        action="BUY",
        symbol="ETH",
        snapshot=ExternalSnapshot(vol_regime="low"),
        gates=gates,
    )
    assert block is not None
    assert "vol_regime_filtered" in block

    # "normal" passes.
    assert apply_external_gates(
        action="BUY",
        symbol="ETH",
        snapshot=ExternalSnapshot(vol_regime="normal"),
        gates=gates,
    ) is None


def test_apply_external_gates_empty_config_passes_everything() -> None:
    from src.config import ExternalSignalsConfig
    from src.external_signals import ExternalSnapshot, apply_external_gates

    gates = ExternalSignalsConfig()  # all defaults: every gate disabled
    snap = ExternalSnapshot(
        fear_greed_index=10,
        btc_dominance_pct=80.0,
        btc_dominance_pct_24h_ago=50.0,
        vol_regime="low",
    )
    assert apply_external_gates(
        action="BUY", symbol="ETH", snapshot=snap, gates=gates
    ) is None


def test_actionability_external_gate_downgrades_buy_to_hold() -> None:
    from src.actionability import apply_actionability_gates
    from src.config import (
        ExternalSignalsConfig,
        get_settings,
    )
    from src.external_signals import ExternalSnapshot
    from src.schemas import EnsembleResult, Features, StrategyVote

    base = get_settings()
    cfg = base.config.model_copy(
        update={
            "external_signals": ExternalSignalsConfig(
                block_buy_if_fear_greed_lt=25
            ),
        }
    )
    settings = base.model_copy(update={"config": cfg})

    feats = Features(
        symbol="ETH",
        last_price=2_500.0,
        bid=2_499.5,
        ask=2_500.5,
        spread_bps=4.0,
        return_5m=0.001,
        return_15m=0.002,
        return_1h=0.005,
        volatility_15m=0.005,
        volatility_1h=0.005,
        high_1h=2_510.0,
        low_1h=2_490.0,
        distance_from_high_1h=0.4,
        distance_from_low_1h=0.4,
        volume_1h=10_000.0,
        source="test",
    )
    ensemble = EnsembleResult(
        final_score=0.30,
        action="BUY",
        confidence=0.6,
        suggested_size_usd=50.0,
        votes=[StrategyVote(name="momentum", score=0.4, confidence=0.7)],
        regime="TRENDING_UP",
        rationale="test",
    )
    snap = ExternalSnapshot(fear_greed_index=15)  # extreme fear

    updated, action_record = apply_actionability_gates(
        ensemble=ensemble,
        features=feats,
        position=None,
        liquidity_score=0.7,
        settings=settings,
        external_snapshot=snap,
    )
    assert updated.action == "HOLD"
    assert action_record.reason.startswith("external_gate=")
    assert "fear_greed_lt" in action_record.reason


def test_actionability_external_gate_skipped_when_snapshot_absent() -> None:
    """No external snapshot → existing pre-external behaviour preserved."""
    from src.actionability import apply_actionability_gates
    from src.config import ExternalSignalsConfig, get_settings
    from src.schemas import EnsembleResult, Features, StrategyVote

    base = get_settings()
    cfg = base.config.model_copy(
        update={
            "external_signals": ExternalSignalsConfig(
                block_buy_if_fear_greed_lt=25,
            ),
        }
    )
    settings = base.model_copy(update={"config": cfg})

    feats = Features(
        symbol="ETH",
        last_price=2_500.0,
        bid=2_499.5,
        ask=2_500.5,
        spread_bps=4.0,
        return_5m=0.001,
        return_15m=0.002,
        return_1h=0.005,
        volatility_15m=0.005,
        volatility_1h=0.005,
        high_1h=2_510.0,
        low_1h=2_490.0,
        distance_from_high_1h=0.4,
        distance_from_low_1h=0.4,
        volume_1h=10_000.0,
        source="test",
    )
    ensemble = EnsembleResult(
        final_score=0.30,
        action="BUY",
        confidence=0.6,
        suggested_size_usd=50.0,
        votes=[StrategyVote(name="momentum", score=0.4, confidence=0.7)],
        regime="TRENDING_UP",
        rationale="test",
    )

    updated, action_record = apply_actionability_gates(
        ensemble=ensemble,
        features=feats,
        position=None,
        liquidity_score=0.7,
        settings=settings,
        external_snapshot=None,  # missing data — must not block
    )
    assert updated.action == "BUY"
    assert action_record.buy_eligible is True
    assert "external_gate" not in (action_record.reason or "")
