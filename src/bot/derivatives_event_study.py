"""Phase 26B — derivatives crowding event studies (cache-only, no network).

Inference contract (aligné sur les phases 6-13)
-----------------------------------------------
Jusqu'à la Phase 30 ce module ne portait **aucun** test d'inférence : son
unique filtre était un seuil brut non pré-enregistré de 0,15 pp appliqué en
*valeur absolue* sur l'excès de rendement. Deux défauts en découlaient :

1. Un excès **négatif** (ex. -1,53 pp) comptait comme preuve favorable d'un
   signal haussier — le gate ``proceed_to_overlay`` rendait ``True`` sur des
   bundles dont les seules « preuves » pointaient dans le mauvais sens.
2. Aucune p-value, aucun placebo, aucune correction multi-tests : sur 6
   signaux × 3 horizons la famille compte jusqu'à 18 tests, où un excès de
   0,15 pp sur n=9 observations est du bruit pur.

Le pipeline applique désormais les mêmes gates que ``scripts/_event_study_*``
(cf. ``docs/SIGNAL_REJECTION_POLICY.md``), dans cet ordre et en court-circuit :

``power`` → ``direction`` → ``inference`` → ``economic``

- **power** : plancher explicite de :data:`MIN_EVENTS_FOR_INFERENCE` événements.
  Sous ce plancher aucune p-value n'est calculée — le rejet est imputé à la
  puissance, jamais à l'inférence.
- **direction** : la direction attendue doit être **pré-enregistrée** dans
  :class:`EventStudySpec`. Aucun des détecteurs actuels n'est directionnel (ils
  déclenchent symétriquement sur les deux queues), donc ``expected_direction``
  vaut ``None`` et le gate le dit explicitement au lieu de laisser un excès
  négatif passer pour une preuve haussière.
- **inference** : p-value bootstrap (ancres aléatoires tirées du même index de
  candles, :func:`src.research.placebo.run_placebo_bootstrap`) puis correction
  Benjamini-Hochberg sur toute la famille de tests d'un même bundle.
- **economic** : l'excès doit dépasser le round-trip taker conservateur du
  gate G3 (:data:`ECONOMIC_EXCESS_FLOOR_PCT`), pas un seuil cosmétique.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from src.bot.crowding_overlay import (
    DEFAULT_FUNDING_MAX_STALENESS_S,
    DEFAULT_OI_MAX_STALENESS_S,
    _align_series,
    _rolling_z_status,
    staleness_bound_for,
)
from src.data.collectors.binance_derivatives_public import (
    LIQUIDATIONS_BLOCKED_REASON,
    LIQUIDATIONS_STATUS,
    default_funding_cache_path,
    default_oi_cache_path,
    load_derivatives_cache,
)
from src.research.placebo import (
    benjamini_hochberg,
    random_events_from_candles,
    run_placebo_bootstrap,
)

SeriesStatus = Literal["available", "blocked_data"]
ExpectedDirection = Literal["long", "short"]
GateLayer = Literal["power", "direction", "inference", "economic"]

# Base sur laquelle la direction attendue est (ou n'est pas) pré-enregistrée.
# Distinguer ces cas est le fond du sujet : "personne ne l'a écrite" est une
# dette documentaire réparable, "le détecteur est symétrique" et "l'hypothèse
# porte sur la volatilité" sont des **propriétés du signal** qu'aucune
# déclaration ne peut lever sans redéfinir le détecteur.
DirectionBasis = Literal[
    "pre_registered",  # direction signée, fixée avant de regarder le résultat
    "symmetric_detector",  # déclenche sur les deux queues -> à scinder d'abord
    "volatility_hypothesis",  # prédit |move|, pas son signe -> mauvais test
    "feed_blocked",  # le feed nécessaire n'existe pas -> rien à pré-enregistrer
    "not_registered",  # dette documentaire : personne n'a écrit d'hypothèse
]
DIRECTION_BASES: tuple[DirectionBasis, ...] = (
    "pre_registered",
    "symmetric_detector",
    "volatility_hypothesis",
    "feed_blocked",
    "not_registered",
)

FORWARD_HORIZONS_HOURS: tuple[int, ...] = (4, 24, 72)

# Plancher de puissance G0. Le document historique exigeait n>=5, ce qui laisse
# passer des « signaux » à 9-11 observations dont l'erreur-type dépasse l'effet
# mesuré. Les red teams du dépôt exigent n>=30 à 40 : on retient 30, borne basse
# où l'approximation normale du bootstrap cesse d'être grossièrement optimiste.
MIN_EVENTS_FOR_INFERENCE = 30

# Round-trip taker conservateur du gate G3 (0,40 % par jambe, cf.
# docs/SIGNAL_REJECTION_POLICY.md). Un excès sous ce plancher est un edge
# illusoire même s'il est statistiquement significatif.
ECONOMIC_EXCESS_FLOOR_PCT = 0.80

DEFAULT_N_PLACEBOS = 200
DEFAULT_PLACEBO_SEED = 20260519
DEFAULT_FDR_ALPHA = 0.05

GATE_LAYERS: tuple[GateLayer, ...] = ("power", "direction", "inference", "economic")


@dataclass(frozen=True)
class EventStudySpec:
    signal_id: str
    description: str
    requires_liquidations: bool = False
    # Direction pré-enregistrée du rendement forward attendu. ``None`` = non
    # pré-enregistrée : le gate `direction` rejette et le dit, plutôt que
    # d'accepter n'importe quel signe d'excès comme confirmation.
    expected_direction: ExpectedDirection | None = None
    # Pourquoi cette direction (ou son absence) — champ **obligatoire dans les
    # faits** : chaque détecteur doit déclarer sur quelle base sa direction est,
    # ou n'est pas, pré-enregistrable. Un `None` par défaut se lit sinon comme
    # un oubli de saisie, alors que c'est une propriété du détecteur.
    direction_basis: DirectionBasis = "not_registered"
    direction_note: str = "expected direction not pre-registered"


PHASE26_EVENT_SPECS: tuple[EventStudySpec, ...] = (
    EventStudySpec(
        "funding_extreme",
        "Funding percentile extreme (crowding)",
        direction_basis="symmetric_detector",
        direction_note=(
            "fires on percentile <=10% (crowded shorts -> bullish reversion) AND "
            ">=90% (crowded longs -> bearish reversion); the two halves predict "
            "opposite signs and their union has no signed expectation. Testable "
            "only after splitting into funding_extreme_high/_low"
        ),
    ),
    EventStudySpec(
        "funding_zscore",
        "Funding rolling z-score regime",
        direction_basis="symmetric_detector",
        direction_note=(
            "fires on |z|>=2: z>=+2 and z<=-2 carry opposite crowding sides and "
            "opposite reversion hypotheses; the union is sign-free by construction"
        ),
    ),
    EventStudySpec(
        "oi_expansion_flat_price",
        "OI up + price range flat (leverage build)",
        direction_basis="volatility_hypothesis",
        direction_note=(
            "the documented hypothesis is 'leverage builds under a flat tape, a "
            "squeeze becomes likely' — a statement about |move|, not about its "
            "sign; a signed excess-return test does not test this hypothesis at all"
        ),
    ),
    EventStudySpec(
        "oi_zscore_range_compress",
        "OI z-score high + compressed range",
        direction_basis="volatility_hypothesis",
        direction_note=(
            "range compression + OI build is a coiled-spring / volatility-expansion "
            "hypothesis; which side the spring releases is exactly what the "
            "detector does not know"
        ),
    ),
    EventStudySpec(
        "liquidation_spike",
        "Liquidation spike aftershock",
        requires_liquidations=True,
        direction_basis="feed_blocked",
        direction_note=(
            "no liquidation feed is reachable (see DATA_SOURCES.md), so the "
            "long-side / short-side split that would carry the direction cannot "
            "even be observed; pre-registering a direction here would be fiction"
        ),
    ),
    EventStudySpec(
        "funding_oi_disagreement",
        "Funding vs OI directional disagreement",
        direction_basis="symmetric_detector",
        direction_note=(
            "fires on both polarities: (funding z>+1, OI z<-0.5) = crowded longs "
            "deleveraging, vs (funding z<-1, OI z>+0.5) = shorts piling in; the "
            "two imply opposite forward signs and are merged into one event list"
        ),
    ),
)


@dataclass
class ForwardReturnStats:
    horizon_hours: int
    horizon_bars: int
    event_count: int
    mean_return_pct: float
    median_return_pct: float
    sign_rate: float
    baseline_mean_return_pct: float
    excess_mean_pct: float
    # Inférence : ``None`` quand le plancher de puissance n'est pas atteint —
    # on refuse de produire une p-value qu'on ne saurait pas défendre.
    p_value: float | None = None
    n_placebos: int = 0
    p_value_tail: Literal["greater", "less", "two_sided"] | None = None


@dataclass
class SignalEventStudyResult:
    signal_id: str
    status: SeriesStatus
    event_count: int
    blocked_reason: str | None = None
    forward_stats: list[ForwardReturnStats] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class GateVerdict:
    """Verdict détaillé d'un test (signal × horizon).

    ``rejected_by`` nomme la **première** couche qui rejette, pour qu'un rejet
    par manque de puissance ne soit jamais confondu avec un rejet par
    inférence. ``layers`` expose l'état de chaque couche : ``True`` passée,
    ``False`` rejetée, ``None`` non évaluée (court-circuit amont).
    """

    passed: bool
    rejected_by: GateLayer | None
    reason: str | None
    layers: Mapping[GateLayer, bool | None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "rejected_by": self.rejected_by,
            "reason": self.reason,
            "layers": dict(self.layers),
        }

    def layers_text(self) -> str:
        """Compact ``power=pass;direction=fail;...`` rendering (CSV-friendly)."""
        marks = {True: "pass", False: "fail", None: "n/a"}
        return ";".join(f"{layer}={marks[self.layers.get(layer)]}" for layer in GATE_LAYERS)


def evaluate_signal_gates(
    *,
    event_count: int,
    excess_mean_pct: float,
    expected_direction: ExpectedDirection | None,
    p_value: float | None,
    q_value: float | None,
    bh_rejected: bool,
    direction_note: str = "expected direction not pre-registered",
    direction_basis: DirectionBasis = "not_registered",
    min_events: int = MIN_EVENTS_FOR_INFERENCE,
    economic_floor_pct: float = ECONOMIC_EXCESS_FLOOR_PCT,
) -> GateVerdict:
    """Apply the four rejection layers to one ``(signal, horizon)`` test.

    Court-circuit au premier échec : c'est ce qui garantit qu'un signal à n
    insuffisant est imputé à ``power`` et non à ``inference`` (il n'a de toute
    façon pas de p-value, faute d'avoir été bootstrappé).
    """
    layers: dict[GateLayer, bool | None] = dict.fromkeys(GATE_LAYERS)

    layers["power"] = event_count >= min_events
    if not layers["power"]:
        return GateVerdict(
            passed=False,
            rejected_by="power",
            reason=f"n={event_count} < power floor {min_events}",
            layers=layers,
        )

    if expected_direction is None:
        layers["direction"] = False
        return GateVerdict(
            passed=False,
            rejected_by="direction",
            reason=(
                "expected direction not pre-registered "
                f"[basis={direction_basis}] ({direction_note})"
            ),
            layers=layers,
        )
    if expected_direction == "long" and excess_mean_pct <= 0.0:
        layers["direction"] = False
        return GateVerdict(
            passed=False,
            rejected_by="direction",
            reason=(
                f"excess {excess_mean_pct:+.4f} pp contradicts the pre-registered "
                "long direction"
            ),
            layers=layers,
        )
    if expected_direction == "short" and excess_mean_pct >= 0.0:
        layers["direction"] = False
        return GateVerdict(
            passed=False,
            rejected_by="direction",
            reason=(
                f"excess {excess_mean_pct:+.4f} pp contradicts the pre-registered "
                "short direction"
            ),
            layers=layers,
        )
    layers["direction"] = True

    if p_value is None:
        layers["inference"] = False
        return GateVerdict(
            passed=False,
            rejected_by="inference",
            reason="no bootstrap p-value available",
            layers=layers,
        )
    if not bh_rejected:
        layers["inference"] = False
        q_txt = "n/a" if q_value is None else f"{q_value:.4f}"
        return GateVerdict(
            passed=False,
            rejected_by="inference",
            reason=f"survives no BH-FDR rejection (p={p_value:.4f}, q={q_txt})",
            layers=layers,
        )
    layers["inference"] = True

    layers["economic"] = abs(excess_mean_pct) >= economic_floor_pct
    if not layers["economic"]:
        return GateVerdict(
            passed=False,
            rejected_by="economic",
            reason=(
                f"|excess| {abs(excess_mean_pct):.4f} pp < round-trip cost floor "
                f"{economic_floor_pct:.2f} pp"
            ),
            layers=layers,
        )

    return GateVerdict(passed=True, rejected_by=None, reason=None, layers=layers)


def apply_bundle_inference(
    tests: Sequence[MutableMapping[str, Any]],
    *,
    alpha: float = DEFAULT_FDR_ALPHA,
) -> int:
    """Run Benjamini-Hochberg over the whole family of tests of one bundle.

    Chaque entrée de ``tests`` doit porter une clé ``p_value`` (``None`` =
    non testé, exclu de la famille). Les clés ``q_value`` et ``bh_rejected``
    sont écrites en place. Retourne le nombre de rejets BH.

    La famille est le **bundle entier** (tous les signaux × tous les horizons),
    pas un signal isolé : c'est bien 18 tests corrélés qui sont menés
    simultanément, et corriger signal par signal reviendrait à ne pas corriger.
    """
    testable = [t for t in tests if t.get("p_value") is not None]
    for t in tests:
        t.setdefault("q_value", None)
        t.setdefault("bh_rejected", False)
    if not testable:
        return 0
    bh = benjamini_hochberg([float(t["p_value"]) for t in testable], alpha=alpha)
    for t, q, rejected in zip(testable, bh.q_values, bh.rejected, strict=True):
        t["q_value"] = float(q)
        t["bh_rejected"] = bool(rejected)
    return bh.n_rejected


def _interval_minutes(timeframe: str) -> int:
    tf = timeframe.strip().lower()
    if tf == "4h":
        return 240
    if tf == "1d":
        return 1440
    raise ValueError(f"unsupported timeframe: {timeframe}")


def _horizon_bars(hours: int, interval_minutes: int) -> int:
    bar_hours = interval_minutes / 60.0
    return max(1, int(round(hours / bar_hours)))


def _z_values(values: Sequence[float | None], window: int) -> list[float | None]:
    """Z-scores glissants exploitables, delegues a :mod:`src.bot.crowding_overlay`.

    Ce module hebergeait sa propre copie de l'alignement et du z-score, avec
    les deux memes defauts que ceux corriges dans ``crowding_overlay`` :
    forward-fill illimite et ``pstdev(buf) or 1e-12``. La copie est supprimee ;
    seule reste la traduction du **statut** en valeur exploitable.

    ``flat`` (serie devenue constante, ecart-type nul) devient ``None`` : sur
    une telle serie le z-score n'est pas defini. L'ancien code y renvoyait
    ``(v - mu) / 1e-12`` soit exactement ``0.0``, indiscernable d'un vrai
    "proche de la moyenne" — et, cote percentile, une serie constante faisait
    déclencher ``funding_extreme`` a chaque bougie.
    """
    return [None if status == "flat" else z for z, status in _rolling_z_status(values, window)]


def _percentile_rank(buf: list[float], value: float) -> float:
    if not buf:
        return 0.5
    below = sum(1 for x in buf if x <= value)
    return below / len(buf)


def _forward_return_pct(
    candles: Sequence[Mapping[str, Any]],
    index: int,
    horizon_bars: int,
) -> float | None:
    if index + horizon_bars >= len(candles):
        return None
    c0 = float(candles[index]["close"])
    c1 = float(candles[index + horizon_bars]["close"])
    if c0 <= 0:
        return None
    return (c1 / c0 - 1.0) * 100.0


def _max_dd_proxy_pct(candles: Sequence[Mapping[str, Any]], index: int, horizon_bars: int) -> float | None:
    if index + horizon_bars >= len(candles):
        return None
    peak = float(candles[index]["close"])
    max_dd = 0.0
    for j in range(index, index + horizon_bars + 1):
        c = float(candles[j]["close"])
        if c > peak:
            peak = c
        dd = (peak - c) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)
    return max_dd * 100.0


def _realized_vol_proxy(
    candles: Sequence[Mapping[str, Any]],
    index: int,
    horizon_bars: int,
) -> float | None:
    rets: list[float] = []
    for j in range(index + 1, index + horizon_bars + 1):
        p0 = float(candles[j - 1]["close"])
        p1 = float(candles[j]["close"])
        if p0 > 0:
            rets.append(math.log(p1 / p0))
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets) * 100.0


def _detect_events(
    signal_id: str,
    candles: Sequence[Mapping[str, Any]],
    funding_aligned: list[float | None],
    oi_aligned: list[float | None],
    *,
    z_window: int = 60,
) -> tuple[list[int], list[str]]:
    notes: list[str] = []
    n = len(candles)
    events: list[int] = []
    fund_z = _z_values(funding_aligned, z_window)
    oi_z = _z_values(oi_aligned, z_window)

    if signal_id == "funding_extreme":
        buf: list[float] = []
        for i in range(n):
            v = funding_aligned[i]
            if v is None:
                continue
            buf.append(v)
            if len(buf) > z_window:
                buf.pop(0)
            if len(buf) < 30:
                continue
            pct = _percentile_rank(buf, v)
            if pct >= 0.90 or pct <= 0.10:
                events.append(i)
        notes.append("events=funding percentile <=10% or >=90%")
        return events, notes

    if signal_id == "funding_zscore":
        for i, z in enumerate(fund_z):
            if z is not None and abs(z) >= 2.0:
                events.append(i)
        notes.append("events=|funding z|>=2")
        return events, notes

    if signal_id == "oi_expansion_flat_price":
        for i in range(20, n - 1):
            oz = oi_z[i]
            if oz is None or oz < 1.0:
                continue
            window = candles[i - 5 : i + 1]
            closes = [float(c["close"]) for c in window]
            rng = (max(closes) - min(closes)) / (statistics.mean(closes) or 1.0)
            if rng < 0.01:
                events.append(i)
        notes.append("events=OI z>=1 and 5-bar range <1%")
        return events, notes

    if signal_id == "oi_zscore_range_compress":
        for i in range(20, n):
            oz = oi_z[i]
            if oz is None or oz < 1.5:
                continue
            hi = max(float(candles[i]["high"]) for c in candles[i - 10 : i + 1])
            lo = min(float(candles[i]["low"]) for c in candles[i - 10 : i + 1])
            mid = float(candles[i]["close"])
            if mid > 0 and (hi - lo) / mid < 0.02:
                events.append(i)
        notes.append("events=OI z>=1.5 and 10-bar range <2%")
        return events, notes

    if signal_id == "funding_oi_disagreement":
        for i in range(n):
            fz = fund_z[i]
            oz = oi_z[i]
            if fz is None or oz is None:
                continue
            if (fz > 1.0 and oz < -0.5) or (fz < -1.0 and oz > 0.5):
                events.append(i)
        notes.append("events=funding z and OI z opposite signs (strong)")
        return events, notes

    return events, notes


def _bootstrap_excess_p_value(
    candles: Sequence[Mapping[str, Any]],
    pool_indices: Sequence[int],
    *,
    n_events: int,
    horizon_bars: int,
    baseline_mean: float,
    observed_excess: float,
    expected_direction: ExpectedDirection | None,
    n_placebos: int,
    seed: int,
) -> tuple[float, int, str] | None:
    """Placebo p-value of an excess return, via random re-anchoring.

    Le null testé est « des ancres tirées au hasard dans le même index de
    candles produiraient le même excès ». On réutilise les primitives de
    :mod:`src.research.placebo` (tirage seedé + lissage +1/(n+1)) plutôt que
    d'écrire un bootstrap maison.

    Le tirage se fait **avec remise** parce que certains détecteurs (funding
    percentile) produisent plus d'événements que le pool admissible ne contient
    de dates ; sans remise le tirage serait impossible à égalité de n.
    """
    if n_events <= 0 or not pool_indices:
        return None
    pool_ts = [int(candles[i]["timestamp"]) for i in pool_indices]
    ts_to_index = {ts: idx for idx, ts in zip(pool_indices, pool_ts, strict=True)}

    def _replicate(sub_seed: int) -> float | None:
        picks = random_events_from_candles(
            pool_ts, n_events=n_events, seed=sub_seed, allow_duplicates=True
        )
        rets = [
            r
            for r in (
                _forward_return_pct(candles, ts_to_index[ts], horizon_bars) for ts in picks
            )
            if r is not None
        ]
        if not rets:
            return None
        return statistics.mean(rets) - baseline_mean

    boot = run_placebo_bootstrap(
        observed_metric=observed_excess,
        n_replicates=n_placebos,
        seed=seed,
        placebo_metric_fn=_replicate,
    )
    if boot.p_value.n_placebos == 0:
        return None
    if expected_direction == "long":
        return boot.p_value.one_sided_greater, boot.p_value.n_placebos, "greater"
    if expected_direction == "short":
        return boot.p_value.one_sided_less, boot.p_value.n_placebos, "less"
    return boot.p_value.two_sided, boot.p_value.n_placebos, "two_sided"


def run_signal_event_study(
    signal_id: str,
    candles: Sequence[Mapping[str, Any]],
    funding_rows: Sequence[Mapping[str, Any]],
    oi_rows: Sequence[Mapping[str, Any]],
    *,
    timeframe: str = "4h",
    n_placebos: int = DEFAULT_N_PLACEBOS,
    seed: int = DEFAULT_PLACEBO_SEED,
    min_events: int = MIN_EVENTS_FOR_INFERENCE,
    funding_max_staleness_s: float | None = DEFAULT_FUNDING_MAX_STALENESS_S,
    oi_max_staleness_s: float | None = None,
) -> SignalEventStudyResult:
    spec = next((s for s in PHASE26_EVENT_SPECS if s.signal_id == signal_id), None)
    if spec is None:
        return SignalEventStudyResult(signal_id, "blocked_data", 0, blocked_reason="unknown signal")

    if spec.requires_liquidations:
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason=LIQUIDATIONS_BLOCKED_REASON,
            notes=[LIQUIDATIONS_STATUS],
        )

    if len(candles) < 120:
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason="insufficient candles",
        )

    if not funding_rows and signal_id in (
        "funding_extreme",
        "funding_zscore",
        "funding_oi_disagreement",
    ):
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason="funding cache missing",
        )

    if not oi_rows and signal_id.startswith("oi_"):
        return SignalEventStudyResult(
            signal_id,
            "blocked_data",
            0,
            blocked_reason="open interest cache missing",
        )

    interval = _interval_minutes(timeframe)
    # Forward-fill borne en fraicheur (meme regle que l'overlay crowding) :
    # au-dela, la derniere valeur connue n'informe plus sur l'etat du marche
    # et, recopiee a l'infini, rend la serie constante.
    oi_bound = (
        oi_max_staleness_s
        if oi_max_staleness_s is not None
        else staleness_bound_for(oi_rows, default_s=DEFAULT_OI_MAX_STALENESS_S)
    )
    fund_al = _align_series(
        candles, funding_rows, "funding_rate", max_staleness_s=funding_max_staleness_s
    )
    oi_al = _align_series(candles, oi_rows, "open_interest", max_staleness_s=oi_bound)

    events, notes = _detect_events(signal_id, candles, fund_al, oi_al)
    if len(events) < 5:
        # Sous 5 événements même les statistiques descriptives sont trompeuses ;
        # le plancher de puissance réel (min_events) est appliqué plus bas.
        return SignalEventStudyResult(
            signal_id,
            "available",
            len(events),
            blocked_reason=None,
            notes=notes
            + [
                "too_few_events_for_stats",
                f"below_power_floor: n={len(events)} < {min_events}",
            ],
        )

    max_hb = max(_horizon_bars(h, interval) for h in FORWARD_HORIZONS_HOURS)
    all_indices = list(range(50, len(candles) - max_hb))
    forward_stats: list[ForwardReturnStats] = []

    for hours in FORWARD_HORIZONS_HOURS:
        hb = _horizon_bars(hours, interval)
        ev_rets = [_forward_return_pct(candles, i, hb) for i in events]
        ev_rets = [r for r in ev_rets if r is not None]
        base_rets = [_forward_return_pct(candles, i, hb) for i in all_indices]
        base_rets = [r for r in base_rets if r is not None]
        if not ev_rets:
            continue
        ev_mean = statistics.mean(ev_rets)
        base_mean = statistics.mean(base_rets) if base_rets else 0.0
        excess = ev_mean - base_mean

        # Sous le plancher de puissance (n < min_events), aucune p-value n'est
        # produite : le rejet doit être imputé à la puissance, pas à une
        # inférence qu'on n'avait pas les moyens de conduire.
        #
        # Au-dessus du plancher, la p-value est calculée **même sans direction
        # pré-enregistrée**, mais elle est alors purement descriptive : la
        # couche `direction` rejette en amont et le gate ne la consulte jamais
        # (cf. `evaluate_signal_gates`, qui n'atteint `inference` qu'après
        # `direction`). La publier ne rouvre donc aucun repêchage two-sided —
        # elle rend seulement l'artefact auditable, ce que l'ancien
        # court-circuit empêchait : un lecteur ne pouvait pas distinguer
        # « non testé faute de puissance » de « non testé faute de direction ».
        # `p_value_tail` et `direction_basis` disent lequel des deux.
        p_value: float | None = None
        n_used_placebos = 0
        tail: str | None = None
        admissible = len(ev_rets) >= min_events
        if admissible and n_placebos > 0:
            boot = _bootstrap_excess_p_value(
                candles,
                all_indices,
                n_events=len(ev_rets),
                horizon_bars=hb,
                baseline_mean=base_mean,
                observed_excess=excess,
                expected_direction=spec.expected_direction,
                n_placebos=n_placebos,
                seed=seed + hours,
            )
            if boot is not None:
                p_value, n_used_placebos, tail = boot

        forward_stats.append(
            ForwardReturnStats(
                horizon_hours=hours,
                horizon_bars=hb,
                event_count=len(ev_rets),
                mean_return_pct=round(ev_mean, 4),
                median_return_pct=round(statistics.median(ev_rets), 4),
                sign_rate=round(sum(1 for r in ev_rets if r > 0) / len(ev_rets), 4),
                baseline_mean_return_pct=round(base_mean, 4),
                excess_mean_pct=round(excess, 4),
                p_value=None if p_value is None else round(p_value, 6),
                n_placebos=n_used_placebos,
                p_value_tail=tail,  # type: ignore[arg-type]
            )
        )

    notes = list(notes)
    if spec.expected_direction is None:
        notes.append(
            f"direction_not_preregistered[{spec.direction_basis}]: {spec.direction_note}"
        )
        notes.append("inference_not_run: no admissible signed test without a direction")
    if len(events) < min_events:
        notes.append(f"below_power_floor: n={len(events)} < {min_events}")

    return SignalEventStudyResult(
        signal_id,
        "available",
        len(events),
        forward_stats=forward_stats,
        notes=notes,
    )


def run_all_derivatives_event_studies(
    asset: str,
    candles: Sequence[Mapping[str, Any]],
    *,
    timeframe: str = "4h",
    cache_root: Any = None,
    n_placebos: int = DEFAULT_N_PLACEBOS,
    seed: int = DEFAULT_PLACEBO_SEED,
    alpha: float = DEFAULT_FDR_ALPHA,
    min_events: int = MIN_EVENTS_FOR_INFERENCE,
    economic_floor_pct: float = ECONOMIC_EXCESS_FLOOR_PCT,
) -> dict[str, Any]:
    from pathlib import Path

    root = Path(cache_root) if cache_root is not None else default_funding_cache_path("BTC").parent
    sym = asset.strip().upper().partition("/")[0]
    period = "4h" if timeframe == "4h" else "1d"

    f_rows, _ = load_derivatives_cache(default_funding_cache_path(sym, root))
    o_rows, _ = load_derivatives_cache(default_oi_cache_path(sym, period, root))

    spec_by_id = {s.signal_id: s for s in PHASE26_EVENT_SPECS}
    results: list[dict[str, Any]] = []
    # Famille de tests du bundle : toutes les cellules (signal × horizon) qui
    # ont pu être bootstrappées. BH est appliqué dessus, pas signal par signal.
    family: list[dict[str, Any]] = []

    for spec in PHASE26_EVENT_SPECS:
        r = run_signal_event_study(
            spec.signal_id,
            candles,
            f_rows,
            o_rows,
            timeframe=timeframe,
            n_placebos=n_placebos,
            seed=seed,
            min_events=min_events,
        )
        stat_dicts: list[dict[str, Any]] = []
        for fs in r.forward_stats:
            entry = {
                "horizon_hours": fs.horizon_hours,
                "horizon_bars": fs.horizon_bars,
                "event_count": fs.event_count,
                "mean_return_pct": fs.mean_return_pct,
                "median_return_pct": fs.median_return_pct,
                "sign_rate": fs.sign_rate,
                "baseline_mean_return_pct": fs.baseline_mean_return_pct,
                "excess_mean_pct": fs.excess_mean_pct,
                "p_value": fs.p_value,
                "p_value_tail": fs.p_value_tail,
                "n_placebos": fs.n_placebos,
                "q_value": None,
                "bh_rejected": False,
            }
            stat_dicts.append(entry)
            family.append(entry)
        results.append(
            {
                "signal_id": r.signal_id,
                "status": r.status,
                "event_count": r.event_count,
                "blocked_reason": r.blocked_reason,
                "expected_direction": spec.expected_direction,
                "direction_basis": spec.direction_basis,
                "direction_note": spec.direction_note,
                "forward_stats": stat_dicts,
                "notes": r.notes,
            }
        )

    bh_rejected_count = apply_bundle_inference(family, alpha=alpha)

    rejection_breakdown: dict[str, int] = dict.fromkeys(GATE_LAYERS, 0)
    passing_signals: list[str] = []
    for res in results:
        spec = spec_by_id[res["signal_id"]]
        signal_passes = False
        if not res["forward_stats"]:
            # Un signal sans aucune cellule évaluable (feed bloqué, ou moins de
            # 5 événements : `run_signal_event_study` sort alors avant de
            # calculer la moindre statistique) disparaissait totalement du
            # bilan. Un rejet silencieux n'est pas un rejet documenté : il
            # entre ici comme **un** rejet de niveau signal, imputé à `power`
            # — il n'y a littéralement pas assez d'observations pour tester.
            verdict = evaluate_signal_gates(
                event_count=int(res["event_count"]),
                excess_mean_pct=0.0,
                expected_direction=spec.expected_direction,
                p_value=None,
                q_value=None,
                bh_rejected=False,
                direction_note=spec.direction_note,
                direction_basis=spec.direction_basis,
                min_events=min_events,
                economic_floor_pct=economic_floor_pct,
            )
            reason = verdict.reason
            if res["blocked_reason"]:
                # Préfixe `blocked_data:` explicite : la raison brute décrit la
                # cause côté feed sans jamais nommer le statut, si bien qu'un
                # lecteur (ou un grep) ne pouvait pas distinguer « feed bloqué »
                # d'un simple manque d'événements.
                reason = (
                    f"blocked_data: {res['blocked_reason']} "
                    f"(n={res['event_count']}); {reason}"
                )
            res["gate_passed"] = False
            res["gate_rejected_by"] = verdict.rejected_by
            res["gate_reason"] = reason
            res["gate_layers"] = verdict.layers_text()
            res["gate_scope"] = "signal"
            if verdict.rejected_by is not None:
                rejection_breakdown[verdict.rejected_by] += 1
            continue
        for entry in res["forward_stats"]:
            verdict = evaluate_signal_gates(
                event_count=int(entry["event_count"]),
                excess_mean_pct=float(entry["excess_mean_pct"]),
                expected_direction=spec.expected_direction,
                p_value=entry["p_value"],
                q_value=entry["q_value"],
                bh_rejected=bool(entry["bh_rejected"]),
                direction_note=spec.direction_note,
                direction_basis=spec.direction_basis,
                min_events=min_events,
                economic_floor_pct=economic_floor_pct,
            )
            # Clés plates : ces dicts sont aplatis tels quels dans results.csv.
            entry["gate_passed"] = verdict.passed
            entry["gate_rejected_by"] = verdict.rejected_by
            entry["gate_reason"] = verdict.reason
            entry["gate_layers"] = verdict.layers_text()
            if verdict.passed:
                signal_passes = True
            elif verdict.rejected_by is not None:
                rejection_breakdown[verdict.rejected_by] += 1
        if signal_passes:
            passing_signals.append(res["signal_id"])

    return {
        "asset": sym,
        "timeframe": timeframe,
        "funding_rows": len(f_rows),
        "oi_rows": len(o_rows),
        "liquidations_status": LIQUIDATIONS_STATUS,
        "results": results,
        "inference": {
            "n_placebos": n_placebos,
            "seed": seed,
            "alpha": alpha,
            "min_events": min_events,
            "economic_floor_pct": economic_floor_pct,
            "family_size": len(family),
            "family_tested": sum(1 for t in family if t["p_value"] is not None),
            "bh_rejected": bh_rejected_count,
        },
        "rejection_breakdown": rejection_breakdown,
        "passing_signals": passing_signals,
        "non_trivial_signals": len(passing_signals),
        "proceed_to_overlay": len(passing_signals) > 0,
    }


def classify_event_study_verdict(summary: Mapping[str, Any]) -> str:
    """Honest verdict for a single asset/timeframe bundle."""
    return str(classify_event_study_verdict_detail(summary)["verdict"])


def classify_event_study_verdict_detail(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Verdict + détail du rejet pour un bundle asset/timeframe.

    Le booléen opaque d'origine ne disait pas *pourquoi* un bundle restait
    faible. On expose la couche responsable (puissance / direction / inférence
    / économie) et le compte de rejets par couche.
    """
    funding_rows = int(summary.get("funding_rows", 0))
    oi_rows = int(summary.get("oi_rows", 0))
    breakdown = {k: int(v) for k, v in (summary.get("rejection_breakdown") or {}).items()}
    passing = list(summary.get("passing_signals") or [])
    n_passing = int(summary.get("non_trivial_signals", len(passing)))

    if funding_rows < 100 or oi_rows < 100:
        return {
            "verdict": "blocked_data",
            "rejected_by": "data",
            "reason": f"funding_rows={funding_rows}, oi_rows={oi_rows} (<100)",
            "passing_signals": passing,
            "rejection_breakdown": breakdown,
        }

    if n_passing == 0:
        # La couche dominante est celle qui a rejeté le plus de cellules ;
        # à égalité on garde l'ordre canonique power > direction > inference.
        dominant = None
        if breakdown:
            dominant = max(
                GATE_LAYERS,
                key=lambda layer: (breakdown.get(layer, 0), -GATE_LAYERS.index(layer)),
            )
            if breakdown.get(dominant, 0) == 0:
                dominant = None
        return {
            "verdict": "weak",
            "rejected_by": dominant,
            "reason": (
                "no (signal, horizon) cell passed power/direction/inference/economic"
            ),
            "passing_signals": passing,
            "rejection_breakdown": breakdown,
        }

    if n_passing >= 2:
        return {
            "verdict": "overlay_only",
            "rejected_by": None,
            "reason": f"{n_passing} signals passed all four gates",
            "passing_signals": passing,
            "rejection_breakdown": breakdown,
        }
    # Un unique signal survivant : le bundle reste `weak`, mais **pas** à cause
    # de l'inférence — ce signal-là l'a précisément passée. Imputer le rejet à
    # `inference` était un mensonge d'étiquette dans la fonction dont le propos
    # est de nommer honnêtement la couche fautive. `family_support` n'est pas
    # une couche de `GATE_LAYERS` (celles-ci s'appliquent cellule par cellule) :
    # c'est une exigence de niveau bundle.
    return {
        "verdict": "weak",
        "rejected_by": "family_support",
        "reason": (
            "a single passing signal is not enough to justify an overlay "
            "(the signal itself passed all four gates)"
        ),
        "passing_signals": passing,
        "rejection_breakdown": breakdown,
    }
