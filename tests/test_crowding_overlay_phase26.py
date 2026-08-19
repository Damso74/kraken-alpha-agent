"""Phase 26C — crowding overlay (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

from src.bot.crowding_overlay import (
    CrowdingOverlayStrategy,
    classify_crowding,
    compare_baseline_vs_overlay,
    precompute_crowding_states,
)
from src.bot.phase26_walkforward import classify_phase26_overlay_verdict


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


def test_classify_crowding_block() -> None:
    st = classify_crowding(3.0, 0.1)
    assert st.filter == "block"


def test_compare_overlay_risk_only() -> None:
    cmp = compare_baseline_vs_overlay(
        {"max_drawdown_pct": 20.0, "total_return_pct": 5.0},
        {"max_drawdown_pct": 12.0, "total_return_pct": 4.0},
    )
    assert cmp["improved_risk_only"] is True


def test_phase26_verdict_overlay_only() -> None:
    v = classify_phase26_overlay_verdict(
        {"data_ok": True, "total_return_pct": 5, "max_drawdown_pct": 20},
        {"data_ok": True, "total_return_pct": 4, "max_drawdown_pct": 12},
    )
    assert v == "overlay_only"


def test_crowding_overlay_warmup() -> None:
    from src.bot.phase23_presets import build_phase23_strategy

    inner = build_phase23_strategy("ema_crossover", "4h", "baseline")
    ov = CrowdingOverlayStrategy(inner, "4h")
    assert ov.warmup_bars() >= inner.warmup_bars()


def test_precompute_states_length() -> None:
    candles = _candles(100)
    fund = [{"timestamp": int(c["timestamp"]), "funding_rate": 0.0001} for c in candles[::3]]
    oi = [{"timestamp": int(c["timestamp"]), "open_interest": 1000.0} for c in candles[::3]]
    states = precompute_crowding_states(candles, fund, oi)
    assert len(states) == len(candles)


# --- Defaut #12: forward-fill non borne et z-score nul silencieux -----------


def _funding_rows(candles: list[dict], upto: int, constant: bool = False) -> list[dict]:
    """Funding toutes les 8h (une bougie 4h sur deux), jusqu'a l'index upto."""
    rows = []
    for i, c in enumerate(candles[:upto:2]):
        rate = 0.0001 if constant else 0.0001 * (1 + (i % 5))
        rows.append({"timestamp": int(c["timestamp"]), "funding_rate": rate})
    return rows


def test_funding_forward_fill_stops_at_staleness_bound() -> None:
    """Au-dela de la borne, la valeur est None et la raison dit 'no_data'."""
    candles = _candles(140)
    fund = _funding_rows(candles, upto=80)

    states = precompute_crowding_states(candles, fund, [])

    last = states[-1]
    assert last.funding_z is None
    assert last.reason.startswith("no_derivatives_data")
    # Juste apres la fin du funding, la derniere valeur reste utilisable.
    assert states[79].funding_z is not None


def test_constant_funding_series_is_flat_not_neutral() -> None:
    """Serie constante: z=0.0 mais raison distincte de 'neutral' et de 'no_data'."""
    candles = _candles(80)
    fund = _funding_rows(candles, upto=80, constant=True)

    states = precompute_crowding_states(candles, fund, [])

    last = states[-1]
    assert last.funding_z == 0.0
    assert last.reason.startswith("flat_series")
    assert not last.reason.startswith("no_derivatives_data")


def test_varying_funding_and_oi_keep_data_driven_reason() -> None:
    """Serie normale: comportement inchange, aucune raison degradee."""
    candles = _candles(120)
    fund = _funding_rows(candles, upto=120)
    oi = [
        {"timestamp": int(c["timestamp"]), "open_interest": 1000.0 + (i % 11) * 3.0}
        for i, c in enumerate(candles)
    ]

    states = precompute_crowding_states(candles, fund, oi)

    last = states[-1]
    assert last.funding_z is not None
    assert last.oi_z is not None
    assert not last.reason.startswith(("no_derivatives_data", "partial_data", "flat_series"))
    assert last.filter == classify_crowding(last.funding_z, last.oi_z).filter


def test_classify_crowding_distinguishes_missing_from_zero() -> None:
    missing = classify_crowding(None, None)
    zero = classify_crowding(0.0, 0.0)
    flat = classify_crowding(0.0, 0.0, funding_status="flat", oi_status="flat")
    assert missing.reason.startswith("no_derivatives_data")
    assert zero.reason == "neutral"
    assert flat.reason.startswith("flat_series")
    assert len({missing.reason, zero.reason, flat.reason}) == 3
