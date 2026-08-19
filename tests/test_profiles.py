"""Profile loading and override tests."""

from __future__ import annotations

from src import config as cfg

_BASE = {
    "profile": "balanced",
    "risk": {
        "max_open_positions": 5,
        "max_position_notional_usd": 1500.0,
        "max_trades_per_hour": 20,
    },
    "strategy": {
        "ensemble_weights": {"momentum": 0.4, "breakout": 0.25},
        "min_confidence_to_trade": 0.30,
    },
    "profiles": {
        "balanced": {
            "description": "default",
            "risk": {"max_open_positions": 5, "max_trades_per_hour": 20},
        },
        "aggressive_competition": {
            "description": "more activity",
            "risk": {
                "max_open_positions": 8,
                "max_position_notional_usd": 2500.0,
                "max_trades_per_hour": 40,
            },
            "strategy": {
                "ensemble_weights": {"momentum": 0.45, "breakout": 0.30},
                "min_confidence_to_trade": 0.22,
            },
        },
        "conservative_debug": {
            "description": "tight",
            "risk": {"max_open_positions": 2, "max_trades_per_hour": 6},
            "strategy": {"min_confidence_to_trade": 0.45},
        },
    },
}


def test_load_active_profile_default_is_balanced() -> None:
    merged, active, available = cfg.load_active_profile(_BASE)
    assert active == "balanced"
    assert "aggressive_competition" in available
    assert merged["risk"]["max_open_positions"] == 5
    assert merged["profile_description"] == "default"


def test_load_active_profile_explicit_override() -> None:
    merged, active, available = cfg.load_active_profile(
        _BASE, override="aggressive_competition"
    )
    assert active == "aggressive_competition"
    # overlay wins on existing keys ...
    assert merged["risk"]["max_open_positions"] == 8
    assert merged["risk"]["max_position_notional_usd"] == 2500.0
    assert merged["risk"]["max_trades_per_hour"] == 40
    # ... and existing base keys not mentioned in the overlay are preserved.
    assert merged["strategy"]["ensemble_weights"]["momentum"] == 0.45
    assert merged["strategy"]["ensemble_weights"]["breakout"] == 0.30
    assert merged["strategy"]["min_confidence_to_trade"] == 0.22


def test_unknown_profile_falls_back_to_balanced() -> None:
    merged, active, _ = cfg.load_active_profile(_BASE, override="does_not_exist")
    assert active == "balanced"
    assert merged["risk"]["max_open_positions"] == 5


def test_full_settings_loads_profile_from_yaml(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "aggressive_competition")
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    assert settings.active_profile == "aggressive_competition"
    # Aggressive profile bumps the per-hour rate limiter.
    assert settings.config.risk.max_trades_per_hour == 40
    assert settings.config.risk.max_position_notional_usd == 2500.0
    assert settings.config.strategy.min_confidence_to_trade == 0.22


def test_full_settings_conservative_profile(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "conservative_debug")
    cfg.get_settings.cache_clear()
    settings = cfg.get_settings()
    assert settings.active_profile == "conservative_debug"
    assert settings.config.risk.max_open_positions == 2
    assert settings.config.risk.max_trades_per_hour == 6
