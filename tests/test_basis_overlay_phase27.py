"""Phase 27 — basis collector + overlay (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.bot.basis_crowding_overlay import (
    BasisCrowdingOverlayStrategy,
    classify_basis_crowding,
    classify_funding_only,
    classify_phase27_tournament_verdict,
    compare_overlay_modes,
    precompute_basis_crowding_states,
)
from src.data.collectors.binance_basis_public import (
    audit_basis_readiness,
    build_basis_rows,
    default_basis_cache_path,
    load_basis_cache,
    parse_basis_rows,
    save_basis_cache,
)


def _candles(n: int, step: int = 14400) -> list[dict]:
    t0 = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    return [
        {
            "timestamp": t0 + i * step,
            "open": 100.0 + i * 0.1,
            "high": 101.0 + i * 0.1,
            "low": 99.0 + i * 0.1,
            "close": 100.5 + i * 0.1,
            "volume": 1.0,
        }
        for i in range(n)
    ]


def _spot_perp(n: int, step: int = 14400, basis: float = 0.001) -> tuple[list, list]:
    t0 = int(datetime(2020, 1, 1, tzinfo=UTC).timestamp())
    spot, perp = [], []
    for i in range(n):
        ts = t0 + i * step
        s = 100.0 + i * 0.05
        spot.append({"timestamp": ts, "close": s})
        perp.append({"timestamp": ts, "close": s * (1 + basis)})
    return spot, perp


def test_build_basis_rows() -> None:
    spot, perp = _spot_perp(80)
    rows = build_basis_rows(spot, perp)
    assert len(rows) == 80
    assert abs(rows[-1]["basis_pct"] - 0.001) < 1e-6
    assert "basis_zscore" in rows[-1]


def test_save_load_basis_cache(tmp_path: Path) -> None:
    spot, perp = _spot_perp(120)
    rows = build_basis_rows(spot, perp)
    path = default_basis_cache_path("BTC", "4h", tmp_path)
    save_basis_cache(path, ticker="BTC", timeframe="4h", rows=rows)
    loaded, meta = load_basis_cache(path)
    assert len(loaded) == 120
    assert meta.get("status") == "available"


def test_classify_basis_crowding_block() -> None:
    st = classify_basis_crowding(2.5, 2.5)
    assert st.filter == "block"


def test_classify_funding_only_reduce() -> None:
    st = classify_funding_only(2.0)
    assert st.filter == "reduce"


def test_precompute_basis_states_length() -> None:
    candles = _candles(100)
    fund = [{"timestamp": int(c["timestamp"]), "funding_rate": 0.0001} for c in candles[::2]]
    basis = [
        {
            "timestamp": int(c["timestamp"]),
            "spot_price": 100.0,
            "perp_price": 100.1,
            "basis_pct": 0.001,
            "basis_zscore": 0.5,
            "basis_compression": False,
            "basis_extreme": False,
        }
        for c in candles[::2]
    ]
    states = precompute_basis_crowding_states(
        candles, fund, basis, mode="funding_basis"
    )
    assert len(states) == len(candles)


def test_basis_overlay_warmup() -> None:
    from src.bot.phase23_presets import build_phase23_strategy

    inner = build_phase23_strategy("ema_crossover", "4h", "baseline")
    ov = BasisCrowdingOverlayStrategy(inner, "4h", mode="funding_basis")
    assert ov.warmup_bars() >= inner.warmup_bars()


def test_compare_overlay_modes() -> None:
    baseline = {"max_drawdown_pct": 20.0, "total_return_pct": 5.0}
    fo = {"max_drawdown_pct": 18.0, "total_return_pct": 4.5}
    fb = {"max_drawdown_pct": 14.0, "total_return_pct": 4.8}
    cmp = compare_overlay_modes(baseline, fo, fb)
    assert cmp["best_mode"] in ("funding_basis", "funding_only", "baseline")


def test_phase27_tournament_verdict_overlay_only() -> None:
    baseline = {"data_ok": True, "total_return_pct": 5, "max_drawdown_pct": 20}
    fo = {"data_ok": True, "total_return_pct": 4, "max_drawdown_pct": 12}
    fb = {"data_ok": True, "total_return_pct": 4.5, "max_drawdown_pct": 11}
    v = classify_phase27_tournament_verdict(baseline, fo, fb)
    assert v == "overlay_only"


def test_audit_basis_readiness_blocked(tmp_path: Path) -> None:
    manifest = audit_basis_readiness(["BTC"], cache_dir=tmp_path, min_rows=50)
    assert manifest["available_count"] == 0


def test_parse_basis_rows_dedupes() -> None:
    rows = parse_basis_rows(
        [
            {"timestamp": 1000, "spot_price": 100, "perp_price": 100.5, "basis_pct": 0.005},
            {"timestamp": 1000, "spot_price": 100, "perp_price": 100.6, "basis_pct": 0.006},
        ]
    )
    assert len(rows) == 1
