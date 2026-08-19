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


def test_paper_status_wrapper_labels_mock_transport_as_mock() -> None:
    """Sous transport mock, le wrapper doit etiqueter la sortie comme simulee.

    L'assertion d'origine etait ``using_mock is True or source == "mock"`` : une
    disjonction que ``tests/conftest.py`` (qui force ``KRAKEN_CLI_TRANSPORT=mock``)
    rendait vraie par construction, et qui passait meme si un seul des deux champs
    etait pose. On exige desormais les deux, ce qui detecte une sortie simulee
    partiellement etiquetee.
    """
    from src import kraken_cli

    status = kraken_cli.fetch_paper_status()
    assert isinstance(status, dict)
    assert status["source"] == "mock"
    assert status["using_mock"] is True
    assert isinstance(status["data"], dict)


def test_paper_status_wrapper_labels_real_cli_payload_as_cli(monkeypatch) -> None:
    """Contre-epreuve : sans elle, le test mock ci-dessus ne discrimine rien.

    Si le wrapper etiquetait *tout* en ``mock``, le test precedent passerait
    quand meme. On force donc un ``run_cli`` qui reussit et on verifie que la
    charge utile n'est PAS maquillee en repli simule.
    """
    from src import kraken_cli

    payload = {"balance": {"USD": "10000"}, "open_orders": []}
    monkeypatch.setattr(
        kraken_cli,
        "run_cli",
        lambda *a, **k: kraken_cli.CLIResult(
            ok=True, status="ok", stdout_json=payload, transport="subprocess"
        ),
    )
    status = kraken_cli.fetch_paper_status()
    assert status["source"] == "kraken_cli"
    assert status.get("using_mock") is not True
    assert status["data"] == payload


def test_xstocks_paper_unsupported_detects_stderr(paper_smoke) -> None:
    assert paper_smoke._is_xstocks_paper_unsupported(
        "EQuery:Unknown asset pair", None
    ) is True


def test_xstocks_paper_unsupported_detects_stdout_payload(paper_smoke) -> None:
    payload = {"error": "api", "message": "EQuery:Unknown asset pair"}
    assert paper_smoke._is_xstocks_paper_unsupported("", payload) is True


def test_xstocks_paper_unsupported_ignores_unrelated_errors(paper_smoke) -> None:
    assert paper_smoke._is_xstocks_paper_unsupported("connection refused", None) is False
    assert paper_smoke._is_xstocks_paper_unsupported("", {"error": "auth", "message": "bad key"}) is False
    assert paper_smoke._is_xstocks_paper_unsupported("", None) is False
