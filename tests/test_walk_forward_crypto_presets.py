"""Regression tests for the multi-resolution preset system in
``scripts/walk_forward_crypto.py``.

Why these tests exist
---------------------
The crypto walk-forward driver was extended on 2026-05-18 from a
single ``default`` configuration (240-min × 90d) to three coordinated
presets (``default``, ``60min``, ``15min``) so the operator can rule
out an intra-day or scalping edge that the long-horizon sweep might
have missed. Each preset bundles every coordinate of the sweep
(interval × candles × split × grid × OOS filter) so the CLI flag
stays a single knob and we never silently mix presets.

These tests pin the contract:

- The three preset names exist and expose a stable schema.
- Each preset's grid uses **only one** exit-timer axis (either
  ``max_hold_minutes`` OR ``time_stop_minutes`` but never both),
  because :func:`src.exit_rules._resolve_params` lets
  ``time_stop_minutes`` shadow ``max_hold_minutes`` and gridding both
  would silently double-count the same dimension.
- The 15-min preset relaxes the OOS WR floor to 0.48 (justified by
  the scalping horizon) and bumps the trades floor to 60.
- ``_resolve_preset`` honours CLI overrides on top of preset defaults.
- The ``default`` preset stays exactly as it was on disk before the
  extension so the existing ``data/walk_forward_crypto_results.json``
  artefact remains reproducible bit-for-bit.

The tests are pure-stdlib and never invoke the network or the Kraken
CLI.
"""

from __future__ import annotations

import argparse
import importlib
import math

import pytest

# Importing the driver is safe — it does no network IO at import time.
walk_forward_crypto = importlib.import_module("scripts.walk_forward_crypto")


# ---------------------------------------------------------------------------
# Preset shape contract
# ---------------------------------------------------------------------------


def test_presets_dict_exposes_three_named_presets() -> None:
    presets = walk_forward_crypto.PRESETS
    assert set(presets.keys()) == {"default", "60min", "15min"}


@pytest.mark.parametrize("name", ["default", "60min", "15min"])
def test_each_preset_exposes_required_keys(name: str) -> None:
    p = walk_forward_crypto.PRESETS[name]
    required_keys = {
        "description",
        "interval_minutes",
        "target_candles",
        "train_fraction",
        "grid",
        "default_min_test_trades_count",
        "default_min_test_win_rate",
        "default_min_test_pnl_usd",
        "default_output",
    }
    assert required_keys.issubset(p.keys())
    # Type sanity.
    assert isinstance(p["interval_minutes"], int) and p["interval_minutes"] > 0
    assert isinstance(p["target_candles"], int) and p["target_candles"] > 0
    assert 0.0 < float(p["train_fraction"]) < 1.0
    assert isinstance(p["grid"], dict) and len(p["grid"]) >= 1


# ---------------------------------------------------------------------------
# Resolution contract — interval / depth / split must match the brief
# ---------------------------------------------------------------------------


def test_default_preset_matches_legacy_240min_setup() -> None:
    """Backwards compatibility — the long-horizon sweep keeps the exact
    coordinates that produced ``data/walk_forward_crypto_results.json``.
    """
    p = walk_forward_crypto.PRESETS["default"]
    assert p["interval_minutes"] == 240
    assert p["target_candles"] == 540
    # 360/540 = 0.6667
    assert math.isclose(p["train_fraction"], 360.0 / 540.0, rel_tol=1e-9)
    assert "max_hold_minutes" in p["grid"]
    assert "time_stop_minutes" not in p["grid"]


def test_60min_preset_targets_intra_day_window() -> None:
    p = walk_forward_crypto.PRESETS["60min"]
    assert p["interval_minutes"] == 60
    assert p["target_candles"] == 720  # ~30 days at 60-min
    # 480 train + 240 test → 20d / 10d split.
    assert math.isclose(p["train_fraction"], 480.0 / 720.0, rel_tol=1e-9)


def test_15min_preset_targets_scalping_window() -> None:
    p = walk_forward_crypto.PRESETS["15min"]
    assert p["interval_minutes"] == 15
    assert p["target_candles"] == 720  # ~7.5 days at 15-min
    # Same 480/240 split → 5d / 2.5d.
    assert math.isclose(p["train_fraction"], 480.0 / 720.0, rel_tol=1e-9)


# ---------------------------------------------------------------------------
# One-axis-only rule for the exit-timer dimension
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["default", "60min", "15min"])
def test_grid_never_mixes_max_hold_and_time_stop(name: str) -> None:
    """``time_stop_minutes`` shadows ``max_hold_minutes`` in
    :func:`src.exit_rules._resolve_params`. Gridding both would
    silently double-count the same dimension — the driver guards
    against that by only ever using one axis per preset."""
    grid_keys = set(walk_forward_crypto.PRESETS[name]["grid"].keys())
    has_max_hold = "max_hold_minutes" in grid_keys
    has_time_stop = "time_stop_minutes" in grid_keys
    assert not (has_max_hold and has_time_stop), (
        f"preset {name!r} grids BOTH max_hold_minutes and time_stop_minutes"
    )


def test_60min_preset_uses_time_stop_minutes_axis() -> None:
    """60min is in the crypto-fast-rotation regime; the canonical
    knob there is ``time_stop_minutes``."""
    grid = walk_forward_crypto.PRESETS["60min"]["grid"]
    assert "time_stop_minutes" in grid
    # The grid covers 4 values matching the brief (15..120 minutes).
    assert sorted(grid["time_stop_minutes"]) == [15, 30, 60, 120]


def test_15min_preset_uses_tighter_time_stop_range() -> None:
    """15-min scalping requires a tighter exit timer range — the
    upper end stays bounded so we never hold a position past the
    OOS test window."""
    grid = walk_forward_crypto.PRESETS["15min"]["grid"]
    assert "time_stop_minutes" in grid
    assert sorted(grid["time_stop_minutes"]) == [5, 15, 30, 60]


# ---------------------------------------------------------------------------
# OOS filter contract — 15-min relaxes WR but bumps trades
# ---------------------------------------------------------------------------


def test_default_and_60min_filter_floors_match_brief() -> None:
    for name in ("default", "60min"):
        p = walk_forward_crypto.PRESETS[name]
        assert math.isclose(p["default_min_test_win_rate"], 0.50, rel_tol=1e-9)
        assert p["default_min_test_trades_count"] == 30
        assert math.isclose(p["default_min_test_pnl_usd"], 0.0, abs_tol=1e-9)


def test_15min_preset_relaxes_wr_floor_and_bumps_trades_floor() -> None:
    """Methodological note: scalping in 15-min is dominated by
    micro-range mean-reversion, so a ≥0.50 WR floor is overly strict.
    The trades floor must compensate by demanding more samples."""
    p = walk_forward_crypto.PRESETS["15min"]
    assert math.isclose(p["default_min_test_win_rate"], 0.48, rel_tol=1e-9)
    assert p["default_min_test_trades_count"] == 60
    assert math.isclose(p["default_min_test_pnl_usd"], 0.0, abs_tol=1e-9)


# ---------------------------------------------------------------------------
# _resolve_preset CLI override contract
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> argparse.Namespace:
    """Build an argparse Namespace mirroring the driver's CLI surface
    with the provided overrides on top."""
    base = dict(
        symbols=None,
        grid_preset="default",
        interval=None,
        target_candles=None,
        secondary_interval=walk_forward_crypto.SECONDARY_INTERVAL_MIN,
        secondary_target_candles=walk_forward_crypto.SECONDARY_TARGET_CANDLES,
        skip_secondary=False,
        train_fraction=None,
        initial_cash=10_000.0,
        min_test_pnl_usd=None,
        min_test_win_rate=None,
        min_test_trades_count=None,
        profile=None,
        output=None,
        ohlc_cache=None,
        use_cache_only=False,
        refresh_cache=False,
        quick=False,
        keep_realtime_cooldown=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_resolve_preset_returns_60min_defaults() -> None:
    resolved = walk_forward_crypto._resolve_preset(_make_args(grid_preset="60min"))
    assert resolved["preset_name"] == "60min"
    assert resolved["interval_minutes"] == 60
    assert resolved["target_candles"] == 720
    assert math.isclose(resolved["train_fraction"], 480.0 / 720.0, rel_tol=1e-9)
    assert resolved["min_test_win_rate"] == 0.50
    assert resolved["min_test_trades_count"] == 30
    assert resolved["output"].endswith("walk_forward_crypto_60min_results.json")


def test_resolve_preset_returns_15min_defaults() -> None:
    resolved = walk_forward_crypto._resolve_preset(_make_args(grid_preset="15min"))
    assert resolved["preset_name"] == "15min"
    assert resolved["interval_minutes"] == 15
    assert resolved["target_candles"] == 720
    assert resolved["min_test_win_rate"] == 0.48
    assert resolved["min_test_trades_count"] == 60
    assert resolved["output"].endswith("walk_forward_crypto_15min_results.json")


def test_resolve_preset_cli_override_wins_over_preset_default() -> None:
    """Operator can still override any individual coordinate from the
    CLI — preset values are sane defaults, not hard locks."""
    resolved = walk_forward_crypto._resolve_preset(
        _make_args(
            grid_preset="60min",
            min_test_win_rate=0.55,
            min_test_trades_count=100,
            output="data/custom.json",
        )
    )
    assert resolved["min_test_win_rate"] == 0.55
    assert resolved["min_test_trades_count"] == 100
    assert resolved["output"].endswith("custom.json")


def test_resolve_preset_rejects_invalid_train_fraction() -> None:
    with pytest.raises(SystemExit):
        walk_forward_crypto._resolve_preset(
            _make_args(grid_preset="60min", train_fraction=1.5)
        )


def test_resolve_preset_rejects_non_positive_interval() -> None:
    with pytest.raises(SystemExit):
        walk_forward_crypto._resolve_preset(
            _make_args(grid_preset="60min", interval=0)
        )
