"""Regression tests for new walk-forward override / filter knobs.

Covers:

- ``_build_settings_override`` translates the ``time_stop_minutes``
  override into ``settings.config.exit.time_stop_minutes``.
- ``_build_settings_override`` resets ``time_stop_minutes`` to ``None``
  when ``max_hold_minutes`` is overridden (so the crypto profile's
  hard-coded ``time_stop_minutes`` does not shadow the grid value).
- ``run_walk_forward`` honours ``min_test_trades_count`` as a survivor
  filter (used by ``scripts/walk_forward_crypto.py`` to demand
  statistical significance).
"""

from __future__ import annotations

from src.backtest import _build_settings_override
from src.config import Settings, get_settings
from src.walk_forward import _passes_filter, WindowMetrics


def _base_settings() -> Settings:
    return get_settings()


def test_time_stop_minutes_override_is_applied_to_exit_config() -> None:
    base = _base_settings()
    out = _build_settings_override(base, overrides={"time_stop_minutes": 45.0})
    assert out.config.exit.time_stop_minutes == 45.0


def test_max_hold_minutes_override_clears_time_stop_alias() -> None:
    base = _base_settings()
    seeded = base.model_copy(
        update={
            "config": base.config.model_copy(
                update={
                    "exit": base.config.exit.model_copy(
                        update={"time_stop_minutes": 30.0}
                    )
                }
            )
        }
    )
    out = _build_settings_override(seeded, overrides={"max_hold_minutes": 90.0})
    # ``max_hold_minutes`` wins, ``time_stop_minutes`` cleared.
    assert out.config.exit.max_hold_minutes == 90.0
    assert out.config.exit.time_stop_minutes is None


def test_passes_filter_enforces_min_trades_count() -> None:
    m = WindowMetrics(net_pnl_usd=5.0, win_rate=0.6, trades_count=15)
    assert _passes_filter(m, min_test_pnl_usd=0.0, min_test_win_rate=0.5) is True
    assert (
        _passes_filter(
            m,
            min_test_pnl_usd=0.0,
            min_test_win_rate=0.5,
            min_test_trades_count=30,
        )
        is False
    )
    m_big = WindowMetrics(net_pnl_usd=5.0, win_rate=0.6, trades_count=42)
    assert (
        _passes_filter(
            m_big,
            min_test_pnl_usd=0.0,
            min_test_win_rate=0.5,
            min_test_trades_count=30,
        )
        is True
    )
