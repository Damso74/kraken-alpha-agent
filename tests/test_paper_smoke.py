"""Paper smoke test parsing — never touches the real CLI."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


@pytest.fixture()
def paper_smoke():
    """Load ``scripts/paper_smoke_test.py`` by file path to avoid requiring
    a package init under ``scripts/`` and keep the script directly runnable.
    """
    root = Path(__file__).resolve().parent.parent
    path = root / "scripts" / "paper_smoke_test.py"
    spec = importlib.util.spec_from_file_location("paper_smoke_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_is_initialised_true_for_well_formed_payload(paper_smoke) -> None:
    payload = {
        "source": "kraken_cli",
        "data": {"balance": {"USD": "10000"}, "open_orders": []},
    }
    assert paper_smoke._is_initialised(payload) is True


def test_is_initialised_false_when_mock(paper_smoke) -> None:
    payload = {"source": "mock", "using_mock": True, "data": {"cash_usd": 10000.0}}
    assert paper_smoke._is_initialised(payload) is False


def test_is_initialised_false_when_note_says_not_initialised(paper_smoke) -> None:
    payload = {
        "source": "mock",
        "data": {},
        "note": "paper not initialised",
    }
    assert paper_smoke._is_initialised(payload) is False


def test_is_initialised_false_for_garbage(paper_smoke) -> None:
    assert paper_smoke._is_initialised(None) is False
    assert paper_smoke._is_initialised({}) is False
    assert paper_smoke._is_initialised({"data": "not-a-dict"}) is False


def test_paper_status_wrapper_handles_mock_transport() -> None:
    """In test mode the wrapper is forced to mock — the helper must not raise."""
    from src import kraken_cli

    status = kraken_cli.fetch_paper_status()
    assert isinstance(status, dict)
    # In mock transport the wrapper labels it as a mock fallback.
    assert status.get("using_mock") is True or status.get("source") == "mock"
