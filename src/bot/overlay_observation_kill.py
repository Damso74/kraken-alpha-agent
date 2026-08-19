"""Phase 28 — kill criteria for overlay paper observation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.bot.overlay_shadow_compare import load_shadow_comparisons, summarize_shadow

DEFAULT_STOP_FILE = Path("reports/paper_observation_phase28/STOP_OBSERVATION")


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


def evaluate_overlay_kill(
    state_dir: Path | str,
    *,
    config: OverlayKillConfig | None = None,
    overlay_equity_curve: Sequence[float] | None = None,
    standalone_equity_curve: Sequence[float] | None = None,
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

    if overlay_equity_curve and standalone_equity_curve:
        gap = _rolling_equity_gap(
            overlay_equity_curve, standalone_equity_curve, cfg.rolling_window
        )
        metrics["equity_gap_pct"] = gap
        if gap is not None and gap < cfg.min_equity_vs_standalone_pct:
            reasons.append(f"overlay_underperforms_standalone gap={gap:.2f}pp")

    return OverlayKillResult(should_kill=bool(reasons), reasons=reasons, metrics=metrics)
