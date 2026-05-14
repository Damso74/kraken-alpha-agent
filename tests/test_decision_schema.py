from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.schemas import (
    Decision,
    ExecutionResult,
    Features,
    RiskCheck,
    RiskResult,
    StrategyVote,
)


def _decision_payload() -> dict:
    return {
        "symbol": "TSLAx",
        "action": "BUY",
        "final_score": 0.55,
        "confidence": 0.72,
        "suggested_size_usd": 250.0,
        "approved_size_usd": 250.0,
        "regime": "TRENDING_UP",
        "features": Features(
            symbol="TSLAx",
            last_price=200.0,
            bid=199.95,
            ask=200.05,
            spread_bps=2.5,
            return_5m=0.001,
            return_15m=0.003,
            return_1h=0.008,
            volatility_15m=0.002,
            volatility_1h=0.005,
            high_1h=202.0,
            low_1h=199.0,
            distance_from_high_1h=0.01,
            distance_from_low_1h=0.005,
            volume_1h=5000.0,
        ).model_dump(),
        "votes": [
            StrategyVote(name="momentum", score=0.6, confidence=0.7).model_dump(),
            StrategyVote(name="breakout", score=0.4, confidence=0.5).model_dump(),
            StrategyVote(name="mean_reversion", score=-0.1, confidence=0.2).model_dump(),
        ],
        "risk": RiskResult(
            approved=True,
            reasons=[],
            checks=[RiskCheck(name="allowlist", passed=True)],
            adjusted_size_usd=250.0,
        ).model_dump(),
        "execution": ExecutionResult(
            status="dry_run_logged",
            mode="dry_run",
            symbol="TSLAx",
            action="BUY",
            requested_size_usd=250.0,
        ).model_dump(),
        "mode": "dry_run",
        "rationale": "test",
    }


def test_decision_parses_canonical_payload():
    payload = _decision_payload()
    decision = Decision(**payload)
    assert decision.action == "BUY"
    assert decision.symbol == "TSLAx"
    assert decision.risk.approved is True
    assert decision.execution.status == "dry_run_logged"


def test_decision_round_trip_through_json():
    decision = Decision(**_decision_payload())
    blob = decision.model_dump_json()
    parsed = json.loads(blob)
    assert parsed["symbol"] == "TSLAx"
    restored = Decision.model_validate(parsed)
    assert restored.symbol == decision.symbol
    assert restored.execution.mode == "dry_run"


def test_decision_rejects_invalid_action():
    payload = _decision_payload()
    payload["action"] = "DUMP"
    with pytest.raises(ValidationError):
        Decision(**payload)
