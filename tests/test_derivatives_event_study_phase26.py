"""Phase 26B — derivatives event study (no network)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from src.bot.derivatives_event_study import (
    ECONOMIC_EXCESS_FLOOR_PCT,
    MIN_EVENTS_FOR_INFERENCE,
    PHASE26_EVENT_SPECS,
    apply_bundle_inference,
    classify_event_study_verdict,
    classify_event_study_verdict_detail,
    evaluate_signal_gates,
    run_all_derivatives_event_studies,
    run_signal_event_study,
)
from src.data.collectors.binance_derivatives_public import save_funding_cache, save_oi_cache


def _candles(n: int, step: int = 14400) -> list[dict]:
    t0 = int(datetime(2022, 1, 1, tzinfo=UTC).timestamp())
    out = []
    price = 100.0
    for i in range(n):
        price += 0.05 if i % 7 else -0.02
        out.append(
            {
                "timestamp": t0 + i * step,
                "open": price,
                "high": price + 1,
                "low": price - 1,
                "close": price,
                "volume": 10.0,
            }
        )
    return out


def _seed_derivatives(tmp_path: Path) -> None:
    fund_rows = [
        {"fundingTime": 1_640_000_000 + i * 28800, "fundingRate": f"{0.0001 * (i % 20 - 10)}"}
        for i in range(200)
    ]
    save_funding_cache(tmp_path / "funding_BTC.json", ticker="BTC", rows=fund_rows)
    oi_rows = [
        {"timestamp": 1_640_000_000 + i * 14400, "sumOpenInterest": str(1000 + i * 5)}
        for i in range(200)
    ]
    save_oi_cache(tmp_path / "oi_BTC_4h.json", ticker="BTC", period="4h", rows=oi_rows)


def test_liquidation_signal_blocked() -> None:
    candles = _candles(200)
    r = run_signal_event_study("liquidation_spike", candles, [], [])
    assert r.status == "blocked_data"


def test_funding_event_study_with_cache(tmp_path: Path) -> None:
    _seed_derivatives(tmp_path)
    candles = _candles(250)
    bundle = run_all_derivatives_event_studies(
        "BTC", candles, timeframe="4h", cache_root=tmp_path, n_placebos=20
    )
    assert bundle["funding_rows"] >= 100
    assert bundle["oi_rows"] >= 100
    assert any(s["signal_id"] == "funding_extreme" for s in bundle["results"])


def test_classify_verdict_blocked() -> None:
    assert classify_event_study_verdict({"funding_rows": 0, "oi_rows": 0}) == "blocked_data"


# ---------------------------------------------------------------------------
# Phase 30 — inference gates (power / direction / inference / economic)
# ---------------------------------------------------------------------------


def test_strong_significant_signal_passes_all_gates() -> None:
    """Un excès fort, dans la direction pré-enregistrée, significatif, passe."""
    verdict = evaluate_signal_gates(
        event_count=120,
        excess_mean_pct=2.50,
        expected_direction="long",
        p_value=0.001,
        q_value=0.004,
        bh_rejected=True,
    )
    assert verdict.passed is True
    assert verdict.rejected_by is None
    assert verdict.layers == {
        "power": True,
        "direction": True,
        "inference": True,
        "economic": True,
    }


def test_negative_excess_no_longer_counts_as_favourable_evidence() -> None:
    """Le défaut corrigé : un excès NEGATIF passait le seuil en valeur absolue.

    Sur ETH 4h, oi_expansion_flat_price affichait -1,53 pp et comptait comme
    signal « non trivial ». Il doit désormais être rejeté par la couche
    direction, alors que le même excès en positif passerait.
    """
    negative = evaluate_signal_gates(
        event_count=120,
        excess_mean_pct=-1.5251,
        expected_direction="long",
        p_value=0.001,
        q_value=0.004,
        bh_rejected=True,
    )
    assert negative.passed is False
    assert negative.rejected_by == "direction"
    assert "contradicts" in (negative.reason or "")

    positive = evaluate_signal_gates(
        event_count=120,
        excess_mean_pct=+1.5251,
        expected_direction="long",
        p_value=0.001,
        q_value=0.004,
        bh_rejected=True,
    )
    assert positive.passed is True


def test_undefined_direction_is_stated_explicitly() -> None:
    """Direction non pré-enregistrée : rejet nommé, pas un booléen opaque."""
    verdict = evaluate_signal_gates(
        event_count=120,
        excess_mean_pct=2.5,
        expected_direction=None,
        p_value=0.001,
        q_value=0.004,
        bh_rejected=True,
        direction_note="detector fires on both tails",
    )
    assert verdict.passed is False
    assert verdict.rejected_by == "direction"
    assert "not pre-registered" in (verdict.reason or "")
    assert "both tails" in (verdict.reason or "")


def test_underpowered_signal_is_rejected_on_power_not_inference() -> None:
    """n=9 (cas ETH 4h) doit être imputé à la puissance, pas à l'inférence."""
    verdict = evaluate_signal_gates(
        event_count=9,
        excess_mean_pct=2.5,
        expected_direction="long",
        p_value=None,
        q_value=None,
        bh_rejected=False,
    )
    assert verdict.passed is False
    assert verdict.rejected_by == "power"
    assert verdict.layers["power"] is False
    # Les couches aval ne sont pas évaluées : on ne peut pas dire qu'un signal
    # sans puissance « échoue l'inférence ».
    assert verdict.layers["inference"] is None
    assert verdict.layers["direction"] is None
    assert str(MIN_EVENTS_FOR_INFERENCE) in (verdict.reason or "")


def test_power_floor_is_at_least_thirty() -> None:
    """Le plancher documenté (n>=5) était trop bas face aux red teams n>=30."""
    assert MIN_EVENTS_FOR_INFERENCE >= 30


def test_economic_layer_rejects_significant_but_sub_cost_excess() -> None:
    verdict = evaluate_signal_gates(
        event_count=200,
        excess_mean_pct=0.20,
        expected_direction="long",
        p_value=0.0001,
        q_value=0.0005,
        bh_rejected=True,
    )
    assert verdict.passed is False
    assert verdict.rejected_by == "economic"
    assert verdict.layers["inference"] is True
    assert f"{ECONOMIC_EXCESS_FLOOR_PCT:.2f}" in (verdict.reason or "")


def test_benjamini_hochberg_shrinks_rejections_as_family_grows() -> None:
    """La correction BH doit mordre quand la famille de tests grandit."""
    small = [{"p_value": 0.02}]
    assert apply_bundle_inference(small, alpha=0.05) == 1
    assert small[0]["bh_rejected"] is True

    large = [{"p_value": 0.02}] + [{"p_value": 0.90} for _ in range(19)]
    assert apply_bundle_inference(large, alpha=0.05) == 0
    assert large[0]["bh_rejected"] is False
    assert large[0]["q_value"] is not None and large[0]["q_value"] > 0.02


def test_untested_cells_are_excluded_from_the_bh_family() -> None:
    """Une cellule sans p-value (puissance insuffisante) ne dilue pas la famille."""
    tests = [{"p_value": 0.02}, {"p_value": None}, {"p_value": None}]
    assert apply_bundle_inference(tests, alpha=0.05) == 1
    assert tests[1]["bh_rejected"] is False
    assert tests[1]["q_value"] is None


def test_no_current_signal_has_a_preregistered_direction() -> None:
    """Aucun détecteur Phase 26 n'est directionnel : la doc doit le dire."""
    for spec in PHASE26_EVENT_SPECS:
        assert spec.expected_direction is None
        assert spec.direction_note


def test_bundle_exposes_rejection_detail_and_no_longer_proceeds(tmp_path: Path) -> None:
    """Le gate d'overlay ne rend plus True sur des excès non testés."""
    _seed_derivatives(tmp_path)
    candles = _candles(250)
    bundle = run_all_derivatives_event_studies(
        "BTC", candles, timeframe="4h", cache_root=tmp_path, n_placebos=20
    )
    assert bundle["proceed_to_overlay"] is False
    assert bundle["non_trivial_signals"] == 0
    assert set(bundle["rejection_breakdown"]) == {
        "power",
        "direction",
        "inference",
        "economic",
    }
    assert sum(bundle["rejection_breakdown"].values()) > 0

    cells = [fs for r in bundle["results"] for fs in r["forward_stats"]]
    assert cells, "expected at least one (signal, horizon) cell"
    for cell in cells:
        assert cell["gate_rejected_by"] in {"power", "direction", "inference", "economic"}
        assert cell["gate_reason"]
        assert "power=" in cell["gate_layers"]

    detail = classify_event_study_verdict_detail(bundle)
    assert detail["verdict"] == "weak"
    assert detail["rejected_by"] in {"power", "direction", "inference", "economic"}
    assert classify_event_study_verdict(bundle) == "weak"


def test_bootstrap_p_value_is_computed_above_the_power_floor(tmp_path: Path) -> None:
    """Au-dessus du plancher, chaque cellule porte une p-value bootstrap."""
    _seed_derivatives(tmp_path)
    candles = _candles(250)
    bundle = run_all_derivatives_event_studies(
        "BTC", candles, timeframe="4h", cache_root=tmp_path, n_placebos=20
    )
    tested = [
        fs
        for r in bundle["results"]
        for fs in r["forward_stats"]
        if fs["event_count"] >= MIN_EVENTS_FOR_INFERENCE
    ]
    assert tested, "fixture should produce at least one powered cell"
    for fs in tested:
        assert fs["p_value"] is not None
        assert 0.0 < fs["p_value"] <= 1.0
        assert fs["n_placebos"] > 0
        assert fs["p_value_tail"] == "two_sided"  # no pre-registered direction

    underpowered = [
        fs
        for r in bundle["results"]
        for fs in r["forward_stats"]
        if fs["event_count"] < MIN_EVENTS_FOR_INFERENCE
    ]
    for fs in underpowered:
        assert fs["p_value"] is None
        assert fs["q_value"] is None


# ---------------------------------------------------------------------------
# Phase 30 (tour 2) — jumeaux du défaut z-score + finitions du gate
# ---------------------------------------------------------------------------


def _stale_funding_fixture() -> tuple[list[dict], list[dict], list[dict]]:
    """300 bougies 4h, mais un cache funding qui s'arrête à la bougie 148."""
    candles = _candles(300)
    t0 = int(candles[0]["timestamp"])
    funding = [
        {"timestamp": t0 + i * 28800, "funding_rate": 0.0001 * ((i % 20) - 10)}
        for i in range(75)
    ]
    oi = [{"timestamp": t0 + i * 14400, "open_interest": 1000.0 + i * 5} for i in range(300)]
    return candles, funding, oi


def test_alignment_and_zscore_helpers_are_shared_with_crowding_overlay() -> None:
    """Pas de troisième copie : le module réutilise les primitives corrigées."""
    from src.bot import crowding_overlay, derivatives_event_study

    assert derivatives_event_study._align_series is crowding_overlay._align_series
    assert derivatives_event_study._rolling_z_status is crowding_overlay._rolling_z_status
    assert not hasattr(derivatives_event_study, "_align_series_to_candles")
    assert not hasattr(derivatives_event_study, "_rolling_zscore")


def test_flat_series_has_no_zscore_instead_of_pstdev_epsilon() -> None:
    """``pstdev(buf) or 1e-12`` rendait z=0.0 sur une série dégénérée."""
    from src.bot.derivatives_event_study import _z_values

    zs = _z_values([1.0] * 80, 60)
    assert all(z is None for z in zs), "a constant series has no defined z-score"


def test_forward_fill_beyond_cache_no_longer_fabricates_events() -> None:
    """Le forward-fill non borné inventait des événements après la fin du cache.

    Le cache funding s'arrête à la bougie 148 ; avec une recopie illimitée la
    série devient constante, ``_percentile_rank`` vaut 1.0 sur chacune des
    bougies suivantes et ``funding_extreme`` déclenchait à chaque barre.
    """
    candles, funding, oi = _stale_funding_fixture()
    r = run_signal_event_study(
        "funding_extreme", candles, funding, oi, timeframe="4h", n_placebos=0
    )
    # Aucune bougie au-delà de 148 + 2 intervalles de funding (16h = 4 barres)
    # ne dispose d'une donnée fraîche : le compte ne peut pas les dépasser.
    assert r.event_count <= 153, f"stale forward-fill fabricated events (n={r.event_count})"


def test_signals_without_evaluable_cells_still_enter_the_breakdown(tmp_path: Path) -> None:
    """Un rejet silencieux n'est pas un rejet documenté (résidu tour 2)."""
    _seed_derivatives(tmp_path)
    candles = _candles(250)
    bundle = run_all_derivatives_event_studies(
        "BTC", candles, timeframe="4h", cache_root=tmp_path, n_placebos=20
    )
    silent = [r for r in bundle["results"] if not r["forward_stats"]]
    assert silent, "fixture should contain at least one signal without any cell"
    for res in silent:
        assert res["gate_rejected_by"] == "power"
        assert res["gate_reason"]
        assert "power=fail" in res["gate_layers"]

    n_cells = sum(len(r["forward_stats"]) for r in bundle["results"])
    assert sum(bundle["rejection_breakdown"].values()) == n_cells + len(silent)


def test_blocked_liquidation_signal_is_counted_not_dropped(tmp_path: Path) -> None:
    _seed_derivatives(tmp_path)
    bundle = run_all_derivatives_event_studies(
        "BTC", _candles(250), timeframe="4h", cache_root=tmp_path, n_placebos=20
    )
    liq = next(r for r in bundle["results"] if r["signal_id"] == "liquidation_spike")
    assert liq["status"] == "blocked_data"
    assert liq["gate_rejected_by"] == "power"
    assert "blocked" in (liq["gate_reason"] or "").lower()


def test_single_passing_signal_is_not_blamed_on_the_inference_layer() -> None:
    """``rejected_by='inference'`` mentait : le signal avait PASSÉ l'inférence."""
    summary = {
        "funding_rows": 500,
        "oi_rows": 500,
        "passing_signals": ["funding_extreme"],
        "non_trivial_signals": 1,
        "rejection_breakdown": {"power": 3, "direction": 0, "inference": 5, "economic": 1},
    }
    detail = classify_event_study_verdict_detail(summary)
    assert detail["verdict"] == "weak"
    assert detail["rejected_by"] != "inference"
    assert detail["rejected_by"] == "family_support"
    assert "single" in detail["reason"]


def test_every_spec_declares_an_explicit_direction_basis() -> None:
    """La direction absente doit être un fait déclaré, pas un défaut de champ."""
    from src.bot.derivatives_event_study import DIRECTION_BASES

    for spec in PHASE26_EVENT_SPECS:
        assert spec.direction_basis in DIRECTION_BASES
        assert spec.direction_note
        if spec.direction_basis == "pre_registered":
            assert spec.expected_direction in {"long", "short"}
        else:
            assert spec.expected_direction is None


def test_two_sided_p_value_can_never_make_a_cell_pass(tmp_path: Path) -> None:
    """Une p-value sans direction pré-enregistrée est descriptive, jamais probante.

    Deux exigences s'opposaient ici et cette version tranche pour la plus forte.
    Ne pas *calculer* la p-value rendait l'artefact illisible : on ne pouvait pas
    distinguer « non testé faute de puissance » de « non testé faute de direction ».
    Ce qu'il fallait interdire n'est pas le calcul mais le **repêchage** — qu'une
    p-value two-sided finisse par faire passer une cellule.

    C'est cette propriété-là que le test verrouille : la couche ``direction``
    rejette avant ``inference``, donc aucune cellule sans direction pré-enregistrée
    ne peut passer, quelle que soit sa p-value. Elle est en revanche publiée, avec
    ``p_value_tail == "two_sided"`` qui dit explicitement son statut.
    """
    _seed_derivatives(tmp_path)
    bundle = run_all_derivatives_event_studies(
        "BTC", _candles(250), timeframe="4h", cache_root=tmp_path, n_placebos=20
    )
    cells = [fs for r in bundle["results"] for fs in r["forward_stats"]]
    assert cells

    by_id = {s.signal_id: s for s in PHASE26_EVENT_SPECS}
    directionless = [
        r for r in bundle["results"] if by_id[r["signal_id"]].expected_direction is None
    ]
    assert directionless, "la fixture doit produire des signaux sans direction"
    checked = 0
    for res in directionless:
        for fs in res["forward_stats"]:
            assert fs["gate_passed"] is False
            if fs["event_count"] >= MIN_EVENTS_FOR_INFERENCE:
                # Au-dessus du plancher, la puissance ne peut plus servir
                # d'explication : c'est bien la direction qui rejette.
                assert fs["gate_rejected_by"] == "direction"
                assert fs["p_value"] is not None
                assert fs["p_value_tail"] == "two_sided"
                checked += 1
    assert checked, "la fixture doit produire au moins une cellule puissante sans direction"

    # Aucun signal sans direction ne figure parmi les signaux retenus.
    assert not set(bundle["passing_signals"]) & {r["signal_id"] for r in directionless}


def test_bootstrap_still_runs_when_a_direction_is_pre_registered() -> None:
    """La couche inférence reste opérationnelle dès qu'un test est admissible."""
    from src.bot.derivatives_event_study import _bootstrap_excess_p_value

    candles = _candles(300)
    pool = list(range(50, len(candles) - 20))
    out = _bootstrap_excess_p_value(
        candles,
        pool,
        n_events=40,
        horizon_bars=6,
        baseline_mean=0.0,
        observed_excess=0.5,
        expected_direction="long",
        n_placebos=25,
        seed=7,
    )
    assert out is not None
    p_value, n_placebos, tail = out
    assert 0.0 < p_value <= 1.0
    assert n_placebos > 0
    assert tail == "greater"
