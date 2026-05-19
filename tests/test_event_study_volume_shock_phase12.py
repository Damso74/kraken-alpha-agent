"""Phase 12 volume shock placebo window alignment."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SPEC = importlib.util.spec_from_file_location(
    "event_study_volume_shock",
    _REPO / "scripts" / "event_study_volume_shock.py",
)
_mod = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_mod)


def test_primary_window_is_post_7() -> None:
    assert _mod.PRIMARY_WINDOW.label == "post_7"
    assert _mod.BH_REFERENCE_METRIC == "return"


def test_compute_research_verdict_weak_when_placebos_fail() -> None:
    verdict = _mod.compute_research_verdict(
        n_events=18,
        n_candles=365,
        script_verdict="supported",
        bh_rejected=3,
        shift_p=1.0,
        shuffle_p=1.0,
        best_raw_p=0.01,
    )
    assert verdict == "weak evidence"
