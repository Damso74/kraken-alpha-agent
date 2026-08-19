"""Phase 28 — kill criteria for overlay paper observation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.bot.overlay_shadow_compare import load_shadow_comparisons, summarize_shadow

DEFAULT_STOP_FILE = Path("reports/paper_observation_phase28/STOP_OBSERVATION")

# Statuts explicites de la comparaison overlay vs standalone. Tant que la courbe
# standalone n'etait fournie par aucun appelant, le critere d'underperformance
# etait silencieusement mort: on expose desormais l'impossibilite d'evaluer.
STANDALONE_EVALUATED = "evaluated"
STANDALONE_NOT_EVALUABLE = "not_evaluable"

# Raisons machine-lisibles (vocabulaire unique, partage avec l'agregateur Phase 29).
STANDALONE_REASON_MISSING = "standalone_curve_missing"
STANDALONE_REASON_OVERLAY_MISSING = "overlay_curve_missing"
STANDALONE_REASON_TOO_SHORT = "curve_too_short"
STANDALONE_REASON_INVALID = "invalid_standalone_equity"
# Les deux courbes PERSISTEES (equity_curve.csv vs standalone_equity.csv) n'ont pas
# la meme semantique: cf. l'argumentaire dans aggregate_observation_metrics_phase29.
STANDALONE_REASON_HETEROGENEOUS = "heterogeneous_run_level_curves"


@dataclass
class OverlayKillConfig:
    max_block_rate: float = 0.60
    min_trades_for_judgment: int = 5
    rolling_window: int = 30
    min_equity_vs_standalone_pct: float = -5.0
    stale_data: bool = False
    max_incoherent_blocks: int = 3
    incoherent_funding_z: float = 1.5
    incoherent_basis_z: float = 1.5


@dataclass
class OverlayKillResult:
    should_kill: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


def observation_stop_active(stop_file: Path | str | None = None) -> bool:
    path = Path(stop_file) if stop_file else DEFAULT_STOP_FILE
    return path.is_file()


def write_observation_stop(stop_file: Path | str, reason: str) -> Path:
    path = Path(stop_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(reason.strip() + "\n", encoding="utf-8")
    return path


def _incoherent_blocks(rows: Sequence[Mapping[str, Any]], cfg: OverlayKillConfig) -> int:
    count = 0
    for r in rows:
        if not r.get("overlay_blocks"):
            continue
        fz = r.get("funding_z")
        bz = r.get("basis_z")
        fz_abs = abs(float(fz)) if fz is not None else 0.0
        bz_abs = abs(float(bz)) if bz is not None else 0.0
        if fz_abs < cfg.incoherent_funding_z and bz_abs < cfg.incoherent_basis_z:
            count += 1
    return count


def _rolling_equity_gap(
    overlay_equity: Sequence[float],
    standalone_equity: Sequence[float],
    window: int,
) -> float | None:
    if len(overlay_equity) < 2 or len(standalone_equity) < 2:
        return None
    n = min(len(overlay_equity), len(standalone_equity), window)
    if n < 2:
        return None
    o0, o1 = overlay_equity[-n], overlay_equity[-1]
    s0, s1 = standalone_equity[-n], standalone_equity[-1]
    if s0 <= 0 or s1 <= 0:
        return None
    o_ret = (o1 / o0 - 1.0) * 100.0
    s_ret = (s1 / s0 - 1.0) * 100.0
    return o_ret - s_ret


def standalone_gap_status(
    overlay_equity: Sequence[float] | None,
    standalone_equity: Sequence[float] | None,
    window: int,
    *,
    disabled_reason: str | None = None,
) -> tuple[float | None, str, str]:
    """Return ``(gap_pp, status, reason)`` for the overlay-vs-standalone criterion.

    ``status`` is ``not_evaluable`` with a machine-readable ``reason`` whenever the
    gap cannot be computed, so a missing standalone curve is reported instead of
    silently disabling the kill criterion.

    ``disabled_reason`` permet a un appelant qui SAIT que les deux courbes ne sont
    pas comparables (courbes heterogenes cote agregateur, cf. Phase 30.5) de
    court-circuiter le calcul en conservant le meme vocabulaire de statut, plutot
    que de passer ``None`` et de faire remonter une raison fausse
    (``standalone_curve_missing`` alors que le fichier existe).
    """
    if disabled_reason:
        return None, STANDALONE_NOT_EVALUABLE, disabled_reason
    if not overlay_equity:
        return None, STANDALONE_NOT_EVALUABLE, STANDALONE_REASON_OVERLAY_MISSING
    if not standalone_equity:
        return None, STANDALONE_NOT_EVALUABLE, STANDALONE_REASON_MISSING
    if len(overlay_equity) < 2 or len(standalone_equity) < 2:
        return None, STANDALONE_NOT_EVALUABLE, STANDALONE_REASON_TOO_SHORT
    gap = _rolling_equity_gap(overlay_equity, standalone_equity, window)
    if gap is None:
        return None, STANDALONE_NOT_EVALUABLE, STANDALONE_REASON_INVALID
    return gap, STANDALONE_EVALUATED, ""


def evaluate_overlay_kill(
    state_dir: Path | str,
    *,
    config: OverlayKillConfig | None = None,
    overlay_equity_curve: Sequence[float] | None = None,
    standalone_equity_curve: Sequence[float] | None = None,
    standalone_disabled_reason: str | None = None,
    trade_count: int = 0,
    stop_file: Path | str | None = None,
) -> OverlayKillResult:
    cfg = config or OverlayKillConfig()
    reasons: list[str] = []
    root = Path(state_dir)

    if observation_stop_active(stop_file):
        return OverlayKillResult(True, ["stop_file_active"], {})

    rows = load_shadow_comparisons(root)
    window_rows = rows[-cfg.rolling_window :] if rows else []
    summary = summarize_shadow(window_rows)
    metrics: dict[str, Any] = {"shadow_summary": summary, "trade_count": trade_count}

    if cfg.stale_data:
        reasons.append("stale_derivatives_data")

    if summary["standalone_trades"] >= cfg.min_trades_for_judgment:
        if summary["block_rate_on_signals"] > cfg.max_block_rate:
            reasons.append(
                f"overlay_blocks_too_often rate={summary['block_rate_on_signals']:.2f}"
            )
    elif trade_count < cfg.min_trades_for_judgment and len(rows) >= cfg.rolling_window:
        reasons.append(f"too_few_trades count={trade_count}")

    incoherent = _incoherent_blocks(window_rows, cfg)
    metrics["incoherent_blocks"] = incoherent
    if incoherent >= cfg.max_incoherent_blocks:
        reasons.append(f"incoherent_blocks count={incoherent}")

    gap, gap_status, gap_reason = standalone_gap_status(
        overlay_equity_curve,
        standalone_equity_curve,
        cfg.rolling_window,
        disabled_reason=standalone_disabled_reason,
    )
    metrics["equity_gap_pct"] = gap
    metrics["standalone_comparison"] = {"status": gap_status, "reason": gap_reason}
    if (
        gap_status == STANDALONE_EVALUATED
        and gap is not None
        and gap < cfg.min_equity_vs_standalone_pct
    ):
        reasons.append(f"overlay_underperforms_standalone gap={gap:.2f}pp")

    return OverlayKillResult(should_kill=bool(reasons), reasons=reasons, metrics=metrics)
