"""``scripts/live_preflight.py`` regression tests.

The preflight is read-only — it never sends an order. The tests exercise
fatal-failure paths (missing validate file, shorting enabled, exposure
above 30) and the happy path against a mocked ``validate_live_xstocks``
artefact.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from src import config as cfg


@pytest.fixture()
def preflight_module(monkeypatch):
    """Load the script with a clean module-cache entry per test.

    The script defines a ``@dataclass`` at module level; CPython's
    ``dataclasses`` looks up ``sys.modules[cls.__module__]`` during
    decoration, so we MUST register the module in ``sys.modules`` BEFORE
    calling ``exec_module``.
    """
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "live_preflight.py"
    spec = importlib.util.spec_from_file_location("live_preflight_test", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["live_preflight_test"] = mod
    try:
        spec.loader.exec_module(mod)
        yield mod
    finally:
        sys.modules.pop("live_preflight_test", None)


def _common_env(monkeypatch) -> None:
    monkeypatch.setenv("KRAKEN_API_KEY", "dummy-key-AAAAA")
    monkeypatch.setenv("KRAKEN_API_SECRET", "dummy-secret-BBBBB")
    monkeypatch.setenv("TRADING_MODE", "dry_run")
    monkeypatch.setenv("LIVE_TRADING", "false")
    monkeypatch.setenv("ALLOW_LIVE_ORDERS", "false")
    monkeypatch.setenv("CONFIG_PATH", "config.example.yaml")


def _write_validate(tmp_path: Path, ok: bool = True) -> Path:
    payload = {
        "timestamp": "2026-05-15T13:00:00Z",
        "source": "validate_only",
        "warning": "validate-only, no order submitted",
        "ok": ok,
        "results": [
            {"symbol": "AAPLx/USD", "ok": ok, "exit_code": 0 if ok else 1},
        ],
    }
    p = tmp_path / "validate_live_xstocks_latest.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _write_validate_perps(tmp_path: Path, ok: bool = True) -> Path:
    payload = {
        "timestamp": "2026-05-15T13:00:00Z",
        "source": "validate_only_futures_perps",
        "warning": "validate-only via paper engine",
        "ok": ok,
        "results": [
            {
                "symbol": "AAPLx/USD",
                "futures_symbol": "PF_AAPLXUSD",
                "ok": ok,
                "exit_code": 0 if ok else 1,
            },
        ],
    }
    p = tmp_path / "validate_live_xstocks_perps_latest.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_preflight_fails_if_validate_missing(preflight_module, monkeypatch) -> None:
    _common_env(monkeypatch)
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    monkeypatch.setenv("KRAKEN_FUTURES_API_KEY", "dummy-futures-key-CCCCC")
    monkeypatch.setenv("KRAKEN_FUTURES_API_SECRET", "dummy-futures-secret-DDDDD")
    cfg.get_settings.cache_clear()
    # Point both validate artefacts at a non-existent path so the missing
    # validate check fires regardless of engine.
    missing = Path("/__missing__/never__here__.json")
    monkeypatch.setattr(preflight_module, "VALIDATE_LATEST", missing)
    monkeypatch.setattr(preflight_module, "VALIDATE_PERPS_LATEST", missing)
    rc = preflight_module.main([])
    assert rc == 1


def test_preflight_fails_when_shorting_enabled(preflight_module, monkeypatch, tmp_path) -> None:
    _common_env(monkeypatch)
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    monkeypatch.setenv("KRAKEN_FUTURES_API_KEY", "dummy-futures-key-CCCCC")
    monkeypatch.setenv("KRAKEN_FUTURES_API_SECRET", "dummy-futures-secret-DDDDD")
    monkeypatch.setenv("SHORTING_ENABLED", "true")  # env flag flips the gate
    cfg.get_settings.cache_clear()

    validate_path = _write_validate(tmp_path, ok=True)
    validate_perps_path = _write_validate_perps(tmp_path, ok=True)
    monkeypatch.setattr(preflight_module, "VALIDATE_LATEST", validate_path)
    monkeypatch.setattr(preflight_module, "VALIDATE_PERPS_LATEST", validate_perps_path)
    # Force the YAML half of the gate ON so the preflight's
    # ``shorting_disabled`` check sees True (defence-in-depth: both env
    # and YAML need to be on for actual shorting, but the preflight rejects
    # if YAML is set).
    settings = cfg.get_settings()
    monkeypatch.setattr(settings.config.trading, "shorting_enabled", True)
    monkeypatch.setattr(preflight_module, "_load_settings", lambda: settings)

    rc = preflight_module.main([])
    assert rc == 1


def test_preflight_fails_when_exposure_above_30(preflight_module, monkeypatch, tmp_path) -> None:
    _common_env(monkeypatch)
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    monkeypatch.setenv("KRAKEN_FUTURES_API_KEY", "dummy-futures-key-CCCCC")
    monkeypatch.setenv("KRAKEN_FUTURES_API_SECRET", "dummy-futures-secret-DDDDD")
    cfg.get_settings.cache_clear()

    validate_path = _write_validate(tmp_path, ok=True)
    validate_perps_path = _write_validate_perps(tmp_path, ok=True)
    monkeypatch.setattr(preflight_module, "VALIDATE_LATEST", validate_path)
    monkeypatch.setattr(preflight_module, "VALIDATE_PERPS_LATEST", validate_perps_path)

    # Inflate the exposure cap above 30.
    settings = cfg.get_settings()
    monkeypatch.setattr(settings.config.risk, "max_total_exposure_usd", 100.0)
    monkeypatch.setattr(preflight_module, "_load_settings", lambda: settings)

    rc = preflight_module.main([])
    assert rc == 1


def test_preflight_happy_path(preflight_module, monkeypatch, tmp_path) -> None:
    _common_env(monkeypatch)
    monkeypatch.setenv("KRAKEN_ALPHA_PROFILE", "micro_live_100eur")
    monkeypatch.setenv("KRAKEN_FUTURES_API_KEY", "dummy-futures-key-CCCCC")
    monkeypatch.setenv("KRAKEN_FUTURES_API_SECRET", "dummy-futures-secret-DDDDD")
    cfg.get_settings.cache_clear()
    validate_path = _write_validate(tmp_path, ok=True)
    validate_perps_path = _write_validate_perps(tmp_path, ok=True)
    monkeypatch.setattr(preflight_module, "VALIDATE_LATEST", validate_path)
    monkeypatch.setattr(preflight_module, "VALIDATE_PERPS_LATEST", validate_perps_path)
    rc = preflight_module.main([])
    assert rc == 0
