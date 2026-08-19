"""Wrapper-level tests.

Goals:
- Confirm that ``--asset-class tokenized_asset`` is added for xStocks and only
  for xStocks.
- Confirm that ``orderbook`` is invoked with ``--count`` (not the legacy
  ``--depth``).
- Confirm that the wrapper falls back to mock data when no transport is
  available, without crashing.

The subprocess invocation is mocked so no real network or shell call leaves
the test process.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from src import kraken_cli

# ---------------------------------------------------------------------------
# _augment_args
# ---------------------------------------------------------------------------


def test_augment_args_adds_asset_class_for_xstocks():
    out = kraken_cli._augment_args(["ticker", "AAPLx/USD"])
    assert "--asset-class" in out
    assert "tokenized_asset" in out
    assert "-o" in out and "json" in out


def test_augment_args_keeps_existing_asset_class():
    out = kraken_cli._augment_args(["ticker", "AAPLx/USD", "--asset-class", "tokenized_asset"])
    assert out.count("--asset-class") == 1


def test_augment_args_skips_asset_class_for_non_xstocks():
    out = kraken_cli._augment_args(["ticker", "BTC/USD"])
    assert "--asset-class" not in out
    assert "-o" in out and "json" in out


def test_augment_args_orderbook_uses_count():
    out = kraken_cli._augment_args(["orderbook", "NVDAx/USD", "--count", "10"])
    assert "--count" in out
    assert "--depth" not in out
    assert "--asset-class" in out


def test_augment_args_idempotent_for_output_flag():
    out = kraken_cli._augment_args(["ticker", "AAPLx/USD", "-o", "json"])
    # -o json should appear exactly once.
    assert out.count("-o") == 1
    assert out.count("json") == 1


# ---------------------------------------------------------------------------
# Transport fallback (no subprocess.run gets called)
# ---------------------------------------------------------------------------


def test_run_cli_falls_back_to_mock_when_no_transport(monkeypatch):
    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("mock", None))
    result = kraken_cli.run_cli(["ticker", "AAPLx/USD"])
    assert result.ok is False
    assert result.status == "missing_cli"
    assert result.using_mock is True
    assert result.transport == "mock"


def test_fetch_ticker_returns_mock_when_cli_missing(monkeypatch):
    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("mock", None))
    info = kraken_cli.fetch_ticker("AAPLx")
    assert info["source"] == "mock"
    assert info["using_mock"] is True
    assert info["last"] > 0
    assert "fallback_reason" in info


def test_fetch_orderbook_falls_back_cleanly(monkeypatch):
    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("mock", None))
    book = kraken_cli.fetch_orderbook("TSLAx", count=3)
    assert book["source"] == "mock"
    assert len(book["data"]["bids"]) == 3
    assert len(book["data"]["asks"]) == 3


# ---------------------------------------------------------------------------
# Real subprocess command shape (mocked subprocess.run)
# ---------------------------------------------------------------------------


def _fake_proc(stdout: str = '{"ok":true}', returncode: int = 0, stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(stdout=stdout, stderr=stderr, returncode=returncode)


def test_run_cli_windows_transport_invokes_binary(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return _fake_proc('{"ok":true}')

    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("windows", "C:/fake/kraken.exe"))
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = kraken_cli.run_cli(["ticker", "NVDAx/USD"])
    assert result.ok is True
    assert result.transport == "windows"
    assert captured["cmd"][0] == "C:/fake/kraken.exe"
    assert "--asset-class" in captured["cmd"]
    assert "tokenized_asset" in captured["cmd"]
    assert "-o" in captured["cmd"] and "json" in captured["cmd"]


def test_run_cli_wsl_transport_wraps_in_bash_lc(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return _fake_proc('{"AAPLx/USD":{}}')

    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("wsl", None))
    monkeypatch.setattr(subprocess, "run", fake_run)

    result = kraken_cli.run_cli(["orderbook", "AAPLx/USD", "--count", "5"])
    assert result.ok is True
    assert result.transport == "wsl"
    assert captured["cmd"][:3] == ["wsl", "--", "bash"]
    assert captured["cmd"][3] == "-lc"
    cmd_string = captured["cmd"][4]
    assert cmd_string.startswith("kraken ")
    assert "orderbook" in cmd_string
    assert "--count" in cmd_string
    assert "--asset-class" in cmd_string
    assert "tokenized_asset" in cmd_string
    assert "AAPLx/USD" in cmd_string


def test_place_order_does_not_touch_network_without_transport(monkeypatch):
    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("mock", None))
    result = kraken_cli.place_order(
        mode="paper",
        symbol_pair="AAPLx/USD",
        action="BUY",
        volume=0.1,
    )
    # When the transport is mock the wrapper returns missing_cli without
    # invoking subprocess.run.
    assert result.status == "missing_cli"
    assert result.using_mock is True


def test_validate_live_order_appends_validate_flag(monkeypatch):
    captured: dict = {}

    def fake_run(cmd, *args, **kwargs):
        captured["cmd"] = list(cmd)
        return _fake_proc('{"validated":true}')

    monkeypatch.setattr(kraken_cli, "_decide_transport", lambda: ("windows", "kraken"))
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = kraken_cli.validate_live_order("AAPLx/USD", "BUY", 0.1)
    assert result.ok is True
    assert "--validate" in captured["cmd"]
    assert "--asset-class" in captured["cmd"]


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("AAPLx/USD", True),
        ("TSLAx", True),
        ("BTC/USD", False),
        ("BTCUSD", False),
        ("", False),
        ("NVDAx/EUR", True),
    ],
)
def test_is_xstock_classifier(symbol, expected):
    assert kraken_cli._is_xstock(symbol) is expected
