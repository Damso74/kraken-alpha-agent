"""Phase 11 verdict logic for exchange status deep dive."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "event_study_exchange_status",
    _REPO / "scripts" / "event_study_exchange_status.py",
)
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_mod)

compute_phase11_verdict = _mod.compute_phase11_verdict


def test_verdict_blocked() -> None:
    assert compute_phase11_verdict(n_events=0, bh_rejected_primary=0, raw_p_primary=[], blocked=True) == "blocked"


def test_verdict_kill_zero_events() -> None:
    assert compute_phase11_verdict(n_events=0, bh_rejected_primary=0, raw_p_primary=[]) == "kill"


def test_verdict_weak_under_five() -> None:
    assert (
        compute_phase11_verdict(n_events=3, bh_rejected_primary=0, raw_p_primary=[0.01])
        == "weak evidence"
    )


def test_verdict_candidate_requires_ten_events_and_bh() -> None:
    assert (
        compute_phase11_verdict(n_events=10, bh_rejected_primary=1, raw_p_primary=[0.2])
        == "candidate for OOS"
    )
    assert (
        compute_phase11_verdict(n_events=8, bh_rejected_primary=1, raw_p_primary=[0.2])
        == "weak evidence"
    )


def test_verdict_kill_when_no_signal() -> None:
    assert (
        compute_phase11_verdict(n_events=12, bh_rejected_primary=0, raw_p_primary=[0.5])
        == "kill"
    )
