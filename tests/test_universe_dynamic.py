"""Tests for the dynamic universe filter."""

from __future__ import annotations

from src.ranking import RankedSymbol
from src.universe import build_dynamic_universe


class _UniCfg:
    def __init__(self) -> None:
        self.max_spread_bps = 80
        self.min_volume = 100
        self.min_trade_count = 10
        self.top_n = 3
        self.symbols = ["AAPLx", "TSLAx", "NVDAx", "MSTRx", "HOODx"]


def _make_rank(symbol: str, *, spread_bps: float, volume: float, tc: int, opp: float) -> RankedSymbol:
    return RankedSymbol(
        symbol=symbol,
        pair=f"{symbol}/USD",
        last_price=100.0,
        bid=99.95,
        ask=100.05,
        spread_bps=spread_bps,
        volume_24h=volume,
        trade_count_recent=tc,
        opportunity_score=opp,
        liquidity_score=0.5,
        momentum_score=opp,
    )


def test_dynamic_filter_excludes_wide_spread() -> None:
    cfg = _UniCfg()
    ranked = [
        _make_rank("AAPLx", spread_bps=20, volume=2000, tc=40, opp=0.6),
        _make_rank("MSTRx", spread_bps=300, volume=2000, tc=40, opp=0.9),
    ]
    out = build_dynamic_universe(ranked, cfg)
    assert "AAPLx" in out
    assert "MSTRx" not in out


def test_dynamic_filter_excludes_low_volume_and_trade_count() -> None:
    cfg = _UniCfg()
    ranked = [
        _make_rank("AAPLx", spread_bps=20, volume=2000, tc=40, opp=0.6),
        _make_rank("HOODx", spread_bps=20, volume=10, tc=40, opp=0.5),
        _make_rank("NVDAx", spread_bps=20, volume=2000, tc=3, opp=0.7),
    ]
    out = build_dynamic_universe(ranked, cfg)
    assert "AAPLx" in out
    assert "HOODx" not in out
    assert "NVDAx" not in out


def test_dynamic_filter_excludes_partial_data() -> None:
    cfg = _UniCfg()
    bad = _make_rank("AAPLx", spread_bps=20, volume=2000, tc=40, opp=0.6)
    bad.last_price = 0.0
    ranked = [bad, _make_rank("TSLAx", spread_bps=20, volume=2000, tc=40, opp=0.4)]
    out = build_dynamic_universe(ranked, cfg)
    assert out == ["TSLAx"]


def test_dynamic_filter_picks_top_n_by_abs_opportunity() -> None:
    cfg = _UniCfg()
    cfg.top_n = 2
    ranked = [
        _make_rank("AAPLx", spread_bps=20, volume=2000, tc=40, opp=0.2),
        _make_rank("TSLAx", spread_bps=20, volume=2000, tc=40, opp=-0.8),
        _make_rank("NVDAx", spread_bps=20, volume=2000, tc=40, opp=0.5),
    ]
    out = build_dynamic_universe(ranked, cfg)
    assert out == ["TSLAx", "NVDAx"]


def test_empty_ranking_falls_back_to_static_allowlist() -> None:
    cfg = _UniCfg()
    out = build_dynamic_universe([], cfg)
    assert out[:3] == cfg.symbols[:3]
