#!/usr/bin/env python3
"""Phase 29 — aggregate overlay paper observation metrics (no network)."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.bot.overlay_observation_engine import (
    PHASE28_TARGETS,
    STANDALONE_EQUITY_FILENAME,
    default_state_dir,
    load_standalone_equity,
)
from src.bot.overlay_observation_kill import (
    STANDALONE_EVALUATED,
    STANDALONE_NOT_EVALUABLE,
    STANDALONE_REASON_HETEROGENEOUS,
    STANDALONE_REASON_MISSING,
    OverlayKillConfig,
    evaluate_overlay_kill,
    observation_stop_active,
)
from src.bot.overlay_shadow_compare import load_shadow_comparisons, summarize_shadow

DEFAULT_BASE = REPO_ROOT / "reports" / "paper_observation_phase28"
DEFAULT_OUT = REPO_ROOT / "reports" / "phase29_observation_metrics"
DEFAULT_MD = REPO_ROOT / "reports" / "PHASE29_OBSERVATION_MONITORING.md"
STOP_FILE = DEFAULT_BASE / "STOP_OBSERVATION"

# Capital initial suppose des runs d'observation. Les artefacts persistes
# (state.json, equity_curve.csv) ne memorisent PAS ObservationConfig.cash: la seule
# facon honnete de traiter un capital != 1000 est donc de le passer explicitement
# (--starting-equity), pas de le deviner. La valeur est ensuite l'UNIQUE source du
# denominateur de tous les rendements calcules ici, et elle est reexposee dans
# summary.json (equity.starting_equity_usd) pour que le document soit auto-decrit.
DEFAULT_STARTING_EQUITY = 1000.0


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _read_equity_curve(state_dir: Path) -> list[tuple[int, float]]:
    path = state_dir / "equity_curve.csv"
    if not path.is_file():
        return []
    rows: list[tuple[int, float]] = []
    with path.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append((int(row["timestamp"]), float(row["equity"])))
    return rows


def _read_trades(state_dir: Path) -> list[dict[str, Any]]:
    path = state_dir / "trades.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _read_errors(state_dir: Path) -> list[str]:
    path = state_dir / "errors.log"
    if not path.is_file():
        return []
    return [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _max_drawdown_pct(equities: Sequence[float]) -> float:
    if not equities:
        return 0.0
    peak = equities[0]
    max_dd = 0.0
    for eq in equities:
        peak = max(peak, eq)
        if peak > 0:
            max_dd = max(max_dd, (peak - eq) / peak * 100.0)
    return round(max_dd, 4)


def _return_pct(first: float, last: float) -> float | None:
    if first <= 0:
        return None
    return round((last / first - 1.0) * 100.0, 4)


def _overlay_decision_counts(decisions: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    keys = ("allow", "block", "reduce", "neutral")
    counts = {k: 0 for k in keys}
    for row in decisions:
        decision = str(row.get("overlay_decision", "")).lower()
        if decision in counts:
            counts[decision] += 1
    return counts


def _stale_data_count(decisions: Sequence[Mapping[str, Any]], errors: Sequence[str]) -> int:
    stale = sum(
        1
        for d in decisions
        if str(d.get("derivatives_status", "")).lower() in {"funding_only", "blocked_derivatives"}
    )
    stale += sum(1 for e in errors if "stale" in e.lower())
    return stale


def _missed_upside_proxy(rows: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for i, row in enumerate(rows):
        if not row.get("overlay_blocks"):
            continue
        if i + 1 >= len(rows):
            continue
        if float(rows[i + 1]["price"]) > float(row["price"]):
            count += 1
    return count


def _avoided_drawdown_proxy(rows: Sequence[Mapping[str, Any]]) -> int:
    count = 0
    for i, row in enumerate(rows):
        blocked = bool(row.get("overlay_blocks"))
        reduced = str(row.get("overlay_decision", "")).lower() == "reduce"
        if not blocked and not reduced:
            continue
        if i + 1 >= len(rows):
            continue
        if float(rows[i + 1]["price"]) < float(row["price"]):
            count += 1
    return count


def _standalone_summary(state_dir: Path) -> dict[str, Any]:
    """Courbe standalone persistee par le moteur d'observation — NON comparable.

    Pourquoi aucun ``return_pct`` n'est expose ici (Phase 30.5, residu #1).

    Les deux courbes persistees ont un point par run cron, mais pas la meme
    semantique:

    * ``equity_curve.csv`` est une courbe de COMPTE. ``run_observation_once``
      reconstruit ``portfolio_overlay`` depuis l'etat persiste
      (``bundle.state.cash_usd`` + positions) puis rejoue toute la serie: le
      rendement de la serie est donc COMPOSE une fois par run.
    * ``standalone_equity.csv`` est une courbe de SERIE. ``replay_standalone_baseline``
      repart de ``cfg.cash`` a chaque run: aucune composition.

    Mesure sur 6 runs a cache croissant (voir
    ``test_persisted_curves_are_heterogeneous`` dans
    tests/test_overlay_observation_phase28.py): overlay 1021.62 -> 1136.96 alors que
    le standalone reste fige a 1021.62 — meme strategie, meme serie. Comparer
    ``standalone_return_pct`` a ``overlay_return_pct_from_1k`` revient donc a
    comparer un rendement N-fois-compose a un rendement une-fois: l'alerte
    d'underperformance ne se declenche quasiment jamais sur une serie gagnante, et
    le gap roulant produit un FAUX POSITIF de kill sur une serie perdante.

    Choix retenu: cesser d'exposer la comparaison inter-runs plutot que de rendre
    les courbes homogenes. Justification: l'observation est ARCHIVEE — le
    ``standalone_equity.csv`` deja sur disque contient des points non composes, et
    aucune reecriture de la semantique cote moteur ne peut corriger cet historique
    (aucun cron ne sera relance). La seule comparaison defendable est INTRA-RUN
    (les deux equity curves d'une meme serie, meme base de depart), et elle est
    deja faite par le moteur — c'est elle qui ecrit STOP_OBSERVATION.

    ``usd`` reste expose: c'est un fait brut (equity du standalone sur la serie
    complete du dernier run), ce qui n'est pas comparable c'est le RENDEMENT
    relatif a la courbe overlay.
    """
    curve = load_standalone_equity(state_dir)
    if not curve:
        return {
            "curve": [],
            "usd": None,
            "return_pct": None,
            "status": STANDALONE_NOT_EVALUABLE,
            "reason": STANDALONE_REASON_MISSING,
            "detail": f"{STANDALONE_EQUITY_FILENAME} absent in {state_dir.name}",
        }
    return {
        "curve": curve,
        "usd": round(curve[-1], 4),
        "return_pct": None,
        "status": STANDALONE_NOT_EVALUABLE,
        "reason": STANDALONE_REASON_HETEROGENEOUS,
        "detail": (
            "equity_curve.csv compounds across runs (resumed from persisted state) "
            "while standalone_equity.csv restarts from cfg.cash each run"
        ),
    }


def _kill_status(
    state_dir: Path,
    shadows: Sequence[Mapping[str, Any]],
    trade_count: int,
    standalone_curve: Sequence[float] | None = None,
    standalone_disabled_reason: str | None = None,
) -> dict[str, Any]:
    stale_deriv = any(
        str(r.get("derivatives_status", "")).lower() == "funding_only"
        for r in _load_jsonl(state_dir / "decisions.jsonl")
    )
    equity_values = [eq for _, eq in _read_equity_curve(state_dir)]
    kill = evaluate_overlay_kill(
        state_dir,
        config=OverlayKillConfig(stale_data=stale_deriv),
        overlay_equity_curve=equity_values or None,
        standalone_equity_curve=list(standalone_curve) if standalone_curve else None,
        # Meme (status, reason) que le bloc equity de summary.json: un seul verdict
        # par document, au lieu de "available"/"not_evaluable" contradictoires.
        standalone_disabled_reason=standalone_disabled_reason,
        trade_count=trade_count,
        stop_file=STOP_FILE,
    )
    return {
        "should_kill": kill.should_kill,
        "reasons": kill.reasons,
        "metrics": kill.metrics,
    }


def aggregate_target_metrics(
    state_dir: Path,
    *,
    starting_equity: float = DEFAULT_STARTING_EQUITY,
) -> dict[str, Any]:
    state = _load_json(state_dir / "state.json")
    decisions = _load_jsonl(state_dir / "decisions.jsonl")
    shadows = load_shadow_comparisons(state_dir)
    equity_rows = _read_equity_curve(state_dir)
    trades = _read_trades(state_dir)
    errors = _read_errors(state_dir)
    shadow_summary = summarize_shadow(shadows)
    decision_counts = _overlay_decision_counts(decisions)

    equities = [eq for _, eq in equity_rows]
    overlay_equity = float(state.get("equity", equities[-1] if equities else starting_equity))
    overlay_return = _return_pct(starting_equity, overlay_equity)

    bh_return: float | None = None
    if shadows:
        bh_return = _return_pct(float(shadows[0]["price"]), float(shadows[-1]["price"]))

    standalone = _standalone_summary(state_dir)

    total_decisions = len(decisions)
    reduce_count = decision_counts["reduce"]
    block_rate = shadow_summary["block_rate_on_signals"]
    reduce_rate = round(reduce_count / total_decisions, 4) if total_decisions else 0.0

    return {
        "target": state_dir.name,
        "state_dir": str(state_dir),
        "observation_only": all(d.get("observation_only", True) for d in decisions) if decisions else True,
        "decision_count": total_decisions,
        "shadow_row_count": len(shadows),
        "trade_count": len(trades),
        "overlay_decisions": decision_counts,
        "block_rate_on_signals": block_rate,
        "reduce_rate_on_decisions": reduce_rate,
        "stale_data_count": _stale_data_count(decisions, errors),
        "error_count": len(errors),
        "errors_tail": errors[-5:],
        "equity": {
            "starting_equity_usd": starting_equity,
            "overlay_usd": round(overlay_equity, 4),
            # Nom de cle historique (consomme par le dashboard et le digest Phase 30):
            # il designe le rendement depuis starting_equity_usd, pas depuis 1000 en dur.
            "overlay_return_pct_from_1k": overlay_return,
            "buy_hold_return_pct_proxy": bh_return,
            "standalone_usd": standalone["usd"],
            "standalone_return_pct": standalone["return_pct"],
            "standalone_status": standalone["status"],
            "standalone_status_reason": standalone["reason"],
            "standalone_status_detail": standalone["detail"],
            "max_drawdown_pct": _max_drawdown_pct(equities),
        },
        "shadow_proxies": {
            "missed_upside_bars": _missed_upside_proxy(shadows),
            "avoided_drawdown_bars": _avoided_drawdown_proxy(shadows),
            "blocks": shadow_summary["blocks"],
            "reductions": shadow_summary["reductions"],
        },
        "kill_criteria": _kill_status(
            state_dir,
            shadows,
            len(trades),
            standalone["curve"],
            standalone_disabled_reason=standalone["reason"] or None,
        ),
        "state_meta": {
            "iteration": state.get("iteration"),
            "last_processed_timestamp": state.get("last_processed_timestamp"),
            "mode": state.get("mode"),
        },
    }


def aggregate_all(
    state_base: Path = DEFAULT_BASE,
    *,
    targets: Sequence[tuple[str, str, str]] = PHASE28_TARGETS,
    starting_equity: float = DEFAULT_STARTING_EQUITY,
) -> dict[str, Any]:
    per_target = [
        aggregate_target_metrics(
            default_state_dir(state_base, strategy, variant),
            starting_equity=starting_equity,
        )
        for strategy, variant, _overlay in targets
    ]
    stop_active = observation_stop_active(STOP_FILE)
    any_kill = any(t["kill_criteria"]["should_kill"] for t in per_target)
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "phase": 29,
        "observation_base": str(state_base),
        "stop_observation_active": stop_active,
        "stop_observation_path": str(STOP_FILE),
        "targets": per_target,
        "summary": {
            "target_count": len(per_target),
            "total_decisions": sum(t["decision_count"] for t in per_target),
            "total_trades": sum(t["trade_count"] for t in per_target),
            "any_kill_triggered": any_kill or stop_active,
            "observation_only": all(t["observation_only"] for t in per_target),
        },
    }


def render_monitoring_md(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Phase 29 — Observation monitoring",
        "",
        f"> Generated: {payload['generated_at_utc']} UTC",
        "",
        "> **PAPER OBSERVATION ONLY — no live trading, no Kraken private API.**",
        "",
        "## Global status",
        "",
        f"- Targets: **{payload['summary']['target_count']}**",
        f"- Total decisions: **{payload['summary']['total_decisions']}**",
        f"- Total trades (csv): **{payload['summary']['total_trades']}**",
        f"- STOP_OBSERVATION: **{'ACTIVE' if payload['stop_observation_active'] else 'absent'}**",
        f"- Kill criteria triggered: **{payload['summary']['any_kill_triggered']}**",
        f"- observation_only: **{payload['summary']['observation_only']}**",
        "",
    ]
    for target in payload["targets"]:
        eq = target["equity"]
        od = target["overlay_decisions"]
        kc = target["kill_criteria"]
        sp = target["shadow_proxies"]
        lines.extend(
            [
                f"## {target['target']}",
                "",
                f"- Decisions: {target['decision_count']} | Shadow rows: {target['shadow_row_count']}",
                f"- Trades: {target['trade_count']}",
                f"- Overlay decisions — allow: {od['allow']} | block: {od['block']} | "
                f"reduce: {od['reduce']} | neutral: {od['neutral']}",
                f"- Block rate (on standalone signals): {target['block_rate_on_signals']:.2%}",
                f"- Reduce rate (on decisions): {target['reduce_rate_on_decisions']:.2%}",
                f"- Stale data signals: {target['stale_data_count']} | Errors: {target['error_count']}",
                "",
                "### Equity",
                f"- Overlay: **{eq['overlay_usd']:.2f}** USD "
                f"(return from {eq.get('starting_equity_usd', DEFAULT_STARTING_EQUITY):.0f}: "
                f"{eq['overlay_return_pct_from_1k']}%)",
                f"- B&H return proxy: {eq['buy_hold_return_pct_proxy']}%",
                (
                    f"- Standalone return: {eq['standalone_return_pct']}%"
                    if eq["standalone_status"] == STANDALONE_EVALUATED
                    else (
                        f"- Standalone return: {STANDALONE_NOT_EVALUABLE} "
                        f"({eq['standalone_status_reason']})"
                    )
                ),
                f"- Max drawdown (overlay curve): {eq['max_drawdown_pct']}%",
                "",
                "### Shadow proxies",
                f"- Missed upside bars: {sp['missed_upside_bars']}",
                f"- Avoided drawdown bars: {sp['avoided_drawdown_bars']}",
                f"- Blocks / reductions: {sp['blocks']} / {sp['reductions']}",
                "",
                "### Kill criteria",
                f"- should_kill: **{kc['should_kill']}**",
            ]
        )
        if kc["reasons"]:
            lines.append(f"- reasons: {', '.join(kc['reasons'])}")
        lines.append("")
    lines.extend(
        [
            "## Refresh",
            "",
            "```powershell",
            "python scripts/aggregate_observation_metrics_phase29.py",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(
    payload: dict[str, Any],
    *,
    json_path: Path = DEFAULT_OUT / "summary.json",
    md_path: Path = DEFAULT_MD,
) -> tuple[Path, Path]:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_monitoring_md(payload), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 29 overlay observation metrics aggregator")
    p.add_argument("--state-base", type=Path, default=DEFAULT_BASE)
    p.add_argument("--json-out", type=Path, default=DEFAULT_OUT / "summary.json")
    p.add_argument("--md-out", type=Path, default=DEFAULT_MD)
    p.add_argument(
        "--starting-equity",
        type=float,
        default=DEFAULT_STARTING_EQUITY,
        help="ObservationConfig.cash used by the runs (returns denominator)",
    )
    args = p.parse_args()

    payload = aggregate_all(args.state_base, starting_equity=args.starting_equity)
    json_path, md_path = write_outputs(payload, json_path=args.json_out, md_path=args.md_out)
    print(json.dumps({"summary_json": str(json_path), "monitoring_md": str(md_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
