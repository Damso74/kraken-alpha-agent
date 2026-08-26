from __future__ import annotations

from src.research.edge_promotion import evaluate_edge_promotion


def _health(*, wof_candidate: bool, exe_candidate: bool) -> dict:
    candidate = "candidate_for_forward_observation"
    decision = "REVIEW_REQUIRED"
    return {
        "schema_version": "edge-forward-production-health-v1",
        "healthy": True,
        "credentials_used": False,
        "orders_sent": 0,
        "h_wof_evaluation": {
            "status": candidate if wof_candidate else "collecting",
            "decision": decision if wof_candidate else "NO-GO",
            "ci_verified": wof_candidate,
            "reproduction_verified": wof_candidate,
            "digest": "/evidence/h-wof.json",
            "authorizes_paper_or_live": False,
        },
        "h_exe_evaluation": {
            "status": candidate if exe_candidate else "technical_gate_pending",
            "decision": decision if exe_candidate else "NO-GO",
            "sessions_verified": exe_candidate,
            "raw_replay_verified": exe_candidate,
            "ci_verified": exe_candidate,
            "economic_gates_passed": exe_candidate,
            "authorizes_paper_or_live": False,
        },
    }


def test_execution_edge_alone_never_becomes_paper_candidate() -> None:
    result = evaluate_edge_promotion(_health(wof_candidate=False, exe_candidate=True))
    assert result["status"] == "execution_only_review_candidate"
    assert result["paper_review_candidate"] is False
    assert result["live_review_candidate"] is False
    assert result["safety"]["h_exe_alone_can_authorize_market_risk"] is False


def test_alpha_candidate_still_requires_paper_evidence() -> None:
    result = evaluate_edge_promotion(_health(wof_candidate=True, exe_candidate=False))
    assert result["status"] == "candidate_for_paper_review"
    assert result["paper_review_candidate"] is True
    assert result["live_review_candidate"] is False
    assert "PAPER_OBSERVATION_EVIDENCE_MISSING" in result["reason_codes"]
    assert result["safety"]["authorizes_paper"] is False


def test_four_verified_paper_weeks_only_open_human_micro_live_review() -> None:
    health = _health(wof_candidate=True, exe_candidate=True)
    evidence = {
        "schema_version": "edge-paper-observation-v1",
        "admission_hypothesis": "H-WOF-002",
        "admission_hwof_digest": "/evidence/h-wof.json",
        "complete_weeks": 4,
        "journal_verified": True,
        "net_pnl_after_costs_usd": 1.0,
        "stress_net_pnl_usd": 0.1,
        "within_pre_registered_risk_limits": True,
        "kill_switch_tested": True,
        "credentials_used": False,
        "orders_sent": 0,
        "human_paper_admission_approved": True,
    }
    result = evaluate_edge_promotion(health, paper_evidence=evidence)
    assert result["status"] == "candidate_for_micro_live_review"
    assert result["live_review_candidate"] is True
    assert result["decision"] == "REVIEW_REQUIRED"
    assert result["safety"]["authorizes_live"] is False


def test_unhealthy_operations_fail_closed() -> None:
    health = _health(wof_candidate=True, exe_candidate=True)
    health["healthy"] = False
    result = evaluate_edge_promotion(health)
    assert result["status"] == "shadow_collecting"
    assert result["decision"] == "NO-GO"
    assert "OPERATIONAL_HEALTH_NOT_VERIFIED" in result["reason_codes"]
