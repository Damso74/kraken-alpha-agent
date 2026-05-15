"""Tests for the strict whitelist parser of ``run_futures_cli`` outcomes.

Context (2026-05-15): the previous blacklist approach missed the
``wouldNotReducePosition`` rejection that Kraken Futures emits at the
account/region level for xStocks Perps on PEDSL-CY. Reproduced manually
on the VPS:

    $ kraken futures order buy PF_HOODXUSD 0.05 --type market --yes -o json
    {"order_id":"...","result":"success","status":"wouldNotReducePosition"}
    $ kraken futures order buy PF_XBTUSD 0.0001 --type market --yes -o json
    {"order_id":"...","result":"success","status":"placed"}

The BTC perp on the same account fills normally, while xStocks Perps are
rejected venue-side without raising a non-zero exit code. The parser
must downgrade any unknown ``status`` string to ``ok=False`` so the
audit log and the local portfolio never confuse a rejection with a fill.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import pytest

from src import futures_kraken_cli


def _fake_proc(stdout: str, returncode: int = 0, stderr: str = "") -> Any:
    """Minimal stand-in for ``subprocess.CompletedProcess`` used by the
    futures CLI wrapper. Only the attributes consumed by ``run_futures_cli``
    need to exist."""

    class _P:
        pass

    p = _P()
    p.stdout = stdout
    p.stderr = stderr
    p.returncode = returncode
    return p


@pytest.fixture(autouse=True)
def _force_windows_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip transport autodetection so the parser path is deterministic."""

    monkeypatch.setattr(
        futures_kraken_cli, "_decide_transport", lambda: ("windows", "kraken")
    )


@pytest.mark.parametrize(
    "rejection_status",
    [
        "wouldNotReducePosition",
        "invalidSize",
        "rejected",
        "marketSuspended",
        "insufficientAvailableFunds",
        "iocOrderFailedBecauseItWouldNotBeExecuted",
        "postOrderFailedBecauseItWouldFilled",
        "wouldExecuteSelf",
        "notEnoughMargin",
        "accountSuspended",
        "weirdUndocumentedStatusFromKraken",
    ],
)
def test_unknown_status_is_treated_as_failure(rejection_status: str) -> None:
    """Anything not in ``_SUCCESS_STATUSES`` must downgrade to ok=False
    and propagate the venue status into ``stderr``."""

    payload = {
        "result": "success",
        "status": rejection_status,
        "order_id": "fake-id",
        "sendStatus": {"order_id": "fake-id", "status": rejection_status},
    }
    fake = _fake_proc(stdout=json.dumps(payload), returncode=0)

    with patch.object(futures_kraken_cli.subprocess, "run", return_value=fake):
        result = futures_kraken_cli.run_futures_cli(
            ["order", "buy", "PF_HOODXUSD", "0.05", "--type", "market", "--yes"]
        )

    assert result.ok is False, (
        f"status={rejection_status!r} must mark the result as failed"
    )
    assert result.status == "error"
    assert rejection_status in (result.stderr or "")


@pytest.mark.parametrize(
    "success_status",
    ["placed", "filled", "partiallyFilled", "received", "triggered", "edited", "untouched"],
)
def test_whitelisted_status_stays_successful(success_status: str) -> None:
    """The seven well-known happy-path statuses must keep ``ok=True``."""

    payload = {
        "result": "success",
        "status": success_status,
        "order_id": "fake-id",
    }
    fake = _fake_proc(stdout=json.dumps(payload), returncode=0)

    with patch.object(futures_kraken_cli.subprocess, "run", return_value=fake):
        result = futures_kraken_cli.run_futures_cli(
            ["order", "buy", "PF_XBTUSD", "0.0001", "--type", "market", "--yes"]
        )

    assert result.ok is True, (
        f"status={success_status!r} must keep ok=True"
    )
    assert result.status == "ok"
    assert result.stdout_json == payload


def test_dict_status_is_not_downgraded() -> None:
    """``cancel-after`` returns a dict in ``status`` next to
    ``result="success"``. The parser must not trip on those payloads."""

    payload = {
        "result": "success",
        "status": {"cancelOnly": True, "currentTime": "2026-05-15T20:00:00Z"},
    }
    fake = _fake_proc(stdout=json.dumps(payload), returncode=0)

    with patch.object(futures_kraken_cli.subprocess, "run", return_value=fake):
        result = futures_kraken_cli.run_futures_cli(["cancel-after", "60"])

    assert result.ok is True
    assert result.status == "ok"


def test_missing_status_field_is_not_downgraded() -> None:
    """Plain JSON with no ``status`` (e.g. ``positions`` listing) must
    not be downgraded — the whitelist only inspects string statuses."""

    payload = {
        "result": "success",
        "openPositions": [],
        "serverTime": "2026-05-15T20:00:00Z",
    }
    fake = _fake_proc(stdout=json.dumps(payload), returncode=0)

    with patch.object(futures_kraken_cli.subprocess, "run", return_value=fake):
        result = futures_kraken_cli.run_futures_cli(["positions"])

    assert result.ok is True
    assert result.status == "ok"


def test_place_live_order_propagates_would_not_reduce_position(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: ``place_live_order`` must return ``ok=False`` when the
    venue answers with the misleading ``wouldNotReducePosition`` status,
    so the execution layer never treats it as a fill."""

    payload = {
        "result": "success",
        "status": "wouldNotReducePosition",
        "order_id": "abc-123",
    }
    fake = _fake_proc(stdout=json.dumps(payload), returncode=0)

    with patch.object(futures_kraken_cli.subprocess, "run", return_value=fake):
        result = futures_kraken_cli.place_live_order(
            side="BUY", symbol="PF_HOODXUSD", size=0.05,
        )

    assert result.ok is False
    assert "wouldNotReducePosition" in (result.stderr or "")
