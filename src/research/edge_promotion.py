"""Fail-closed promotion contract for the edge sprint.

H-WOF may establish an alpha candidate. H-EXE may establish an execution
improvement candidate, but can never justify taking market risk on its own.
Every status remains review-only and authorizes neither paper nor live orders.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "edge-promotion-v1"
PAPER_EVIDENCE_SCHEMA = "edge-paper-observation-v1"
MIN_COMPLETE_PAPER_WEEKS = 4


def _is_review_candidate(payload: Mapping[str, Any]) -> bool:
    return (
        payload.get("status") == "candidate_for_forward_observation"
        and payload.get("decision") == "REVIEW_REQUIRED"
        and payload.get("authorizes_paper_or_live") is False
    )


def evaluate_edge_promotion(
    health: Mapping[str, Any],
    *,
    paper_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    reasons: list[str] = []
    operational = (
        health.get("schema_version") == "edge-forward-production-health-v1"
        and health.get("healthy") is True
        and health.get("credentials_used") is False
        and int(health.get("orders_sent", -1)) == 0
    )
    if not operational:
        reasons.append("OPERATIONAL_HEALTH_NOT_VERIFIED")

    h_wof = health.get("h_wof_evaluation", {})
    h_exe = health.get("h_exe_evaluation", {})
    alpha_candidate = (
        isinstance(h_wof, Mapping)
        and _is_review_candidate(h_wof)
        and h_wof.get("ci_verified") is True
        and h_wof.get("reproduction_verified") is True
    )
    execution_candidate = (
        isinstance(h_exe, Mapping)
        and _is_review_candidate(h_exe)
        and h_exe.get("sessions_verified") is True
        and h_exe.get("raw_replay_verified") is True
        and h_exe.get("ci_verified") is True
        and h_exe.get("economic_gates_passed") is True
    )
    if not alpha_candidate:
        reasons.append("H_WOF_ALPHA_NOT_CANDIDATE")
    if not execution_candidate:
        reasons.append("H_EXE_EXECUTION_NOT_CANDIDATE")

    paper_review_candidate = operational and alpha_candidate
    paper_checks = {
        "schema_verified": False,
        "admission_hypothesis_verified": False,
        "admission_digest_verified": False,
        "complete_weeks_at_least_4": False,
        "journal_verified": False,
        "net_after_costs_positive": False,
        "stress_net_positive": False,
        "within_pre_registered_risk_limits": False,
        "kill_switch_tested": False,
        "shadow_only": False,
        "human_paper_admission_recorded": False,
    }
    if paper_evidence is None:
        reasons.append("PAPER_OBSERVATION_EVIDENCE_MISSING")
    else:
        paper_checks = {
            "schema_verified": paper_evidence.get("schema_version") == PAPER_EVIDENCE_SCHEMA,
            "admission_hypothesis_verified": paper_evidence.get("admission_hypothesis")
            == "H-WOF-002",
            "admission_digest_verified": paper_evidence.get("admission_hwof_digest")
            == h_wof.get("digest"),
            "complete_weeks_at_least_4": int(paper_evidence.get("complete_weeks", 0))
            >= MIN_COMPLETE_PAPER_WEEKS,
            "journal_verified": paper_evidence.get("journal_verified") is True,
            "net_after_costs_positive": float(paper_evidence.get("net_pnl_after_costs_usd", 0.0))
            > 0.0,
            "stress_net_positive": float(paper_evidence.get("stress_net_pnl_usd", 0.0)) > 0.0,
            "within_pre_registered_risk_limits": paper_evidence.get(
                "within_pre_registered_risk_limits"
            )
            is True,
            "kill_switch_tested": paper_evidence.get("kill_switch_tested") is True,
            "shadow_only": paper_evidence.get("credentials_used") is False
            and int(paper_evidence.get("orders_sent", -1)) == 0,
            "human_paper_admission_recorded": paper_evidence.get("human_paper_admission_approved")
            is True,
        }
        reasons.extend(
            f"PAPER_{name.upper()}_FAILED" for name, passed in paper_checks.items() if not passed
        )

    live_review_candidate = paper_review_candidate and all(paper_checks.values()) and operational
    if live_review_candidate:
        status = "candidate_for_micro_live_review"
    elif paper_review_candidate:
        status = "candidate_for_paper_review"
    elif operational and execution_candidate:
        status = "execution_only_review_candidate"
    else:
        status = "shadow_collecting"
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "decision": "REVIEW_REQUIRED" if status != "shadow_collecting" else "NO-GO",
        "alpha_candidate": alpha_candidate,
        "execution_candidate": execution_candidate,
        "paper_review_candidate": paper_review_candidate,
        "live_review_candidate": live_review_candidate,
        "paper_evidence_gates": paper_checks,
        "reason_codes": list(dict.fromkeys(reasons)) or ["ALL_REVIEW_GATES_PASSED"],
        "safety": {
            "authorizes_paper": False,
            "authorizes_live": False,
            "authorizes_orders": False,
            "human_review_required": True,
            "h_exe_alone_can_authorize_market_risk": False,
        },
    }
