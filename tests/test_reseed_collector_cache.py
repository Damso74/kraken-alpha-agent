"""Reseed des caches collectors depuis les manifests — tests hermetiques.

Aucun test ne touche le reseau : le fetcher est injecte et leve si une URL
inattendue est demandee. Aucun test n'ecrit dans ``data/collector_cache/`` ni
dans ``reports/`` : tout passe par ``tmp_path``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.reseed_collector_cache import (
    DEFAULT_MANIFESTS,
    STATUS_ABSENT,
    STATUS_ERROR,
    STATUS_MATCH,
    STATUS_MISMATCH,
    STATUS_PRESENT_UNVERIFIED,
    STATUS_REBUILT,
    STATUS_SKIPPED,
    CacheTarget,
    ReseedError,
    classify_filename,
    content_divergences,
    coverage_days_for,
    exit_code_for,
    inspect_cache_file,
    load_targets,
    manifest_basename,
    merge_targets,
    parse_manifest_payload,
    reseed,
    resolve_cache_root,
    sha256_file,
)
from src.data.collectors.binance_derivatives_public import save_oi_cache
from src.data.collectors.binance_public import TIMEFRAME_COVERAGE_DAYS, save_ohlc_cache

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable

WINDOWS_PATH_PREFIX = (
    "C:\\Users\\credo\\Documents\\Code_Informatique\\Projets-en-cours\\"
    "kraken-alpha-agent\\data\\collector_cache\\"
)

NOW = datetime(2026, 8, 19, 12, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------
# Faux fetcher (zero reseau)
# --------------------------------------------------------------------------


class FakeBinance:
    """Genere des payloads Binance plausibles a partir des parametres recus."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, params=None):
        params = dict(params or {})
        self.calls.append((url, params))
        if url.endswith("/api/v3/klines"):
            return self._klines(params)
        if url.endswith("/fapi/v1/markPriceKlines"):
            return self._klines(params, price_offset=25.0)
        if url.endswith("/fapi/v1/fundingRate"):
            return self._funding(params)
        if url.endswith("/futures/data/openInterestHist"):
            return self._open_interest(params)
        raise AssertionError(f"URL inattendue dans un test hermetique: {url}")

    @staticmethod
    def _step_ms(interval: str) -> int:
        return {"1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}[interval]

    def _klines(self, params, *, price_offset: float = 0.0):
        step = self._step_ms(params["interval"])
        start = int(params["startTime"])
        end = int(params["endTime"])
        limit = int(params.get("limit", 1000))
        rows = []
        cursor = start - (start % step)
        while cursor <= end and len(rows) < limit:
            close = 50_000.0 + price_offset + (cursor % 977) / 10.0
            rows.append(
                [
                    cursor,
                    f"{close - 5:.2f}",
                    f"{close + 8:.2f}",
                    f"{close - 9:.2f}",
                    f"{close:.2f}",
                    "12.5",
                    cursor + step - 1,
                    f"{close * 12.5:.2f}",
                    100,
                ]
            )
            cursor += step
        return rows

    @staticmethod
    def _funding(params):
        end = int(params.get("endTime", 0))
        step = 8 * 3_600_000
        return [
            {
                "symbol": params["symbol"],
                "fundingTime": end - i * step,
                "fundingRate": f"{0.0001 * (1 + i % 5):.8f}",
            }
            for i in range(120)
        ]

    @staticmethod
    def _open_interest(params):
        end = int(params.get("endTime", 0))
        step = 14_400_000 if params["period"] == "4h" else 86_400_000
        return [
            {
                "symbol": params["symbol"],
                "timestamp": end - i * step,
                "sumOpenInterest": f"{70000 + i}",
                "sumOpenInterestValue": f"{70000 + i}00",
            }
            for i in range(40)
        ]


def _exploding_fetcher(url, params=None):
    raise AssertionError(f"le fetcher ne devait pas etre appele (url={url})")


# --------------------------------------------------------------------------
# Manifests synthetiques (memes formes que les manifests versionnes)
# --------------------------------------------------------------------------


def _phase24_manifest(sha: str, *, first_ts: int, last_ts: int) -> dict:
    return {
        "phase": 24,
        "cache_root": WINDOWS_PATH_PREFIX.rstrip("\\"),
        "entries": [
            {
                "asset": "BTC",
                "timeframe": "1d",
                "cache_path": WINDOWS_PATH_PREFIX + "ohlc_daily_BTC.json",
                "bar_count": 46,
                "first_timestamp": first_ts,
                "last_timestamp": last_ts,
                "sha256": sha,
                "data_ok": True,
                "blocked_reason": None,
            }
        ],
    }


def _phase21_manifest(sha: str, *, first_ts: int, last_ts: int) -> dict:
    return {
        "generated_at_utc": "2026-05-20T09:22:44Z",
        "entries": [
            {
                "asset": "BTC",
                "timeframe": "1d",
                "cache_path": WINDOWS_PATH_PREFIX + "ohlc_daily_BTC.json",
                "row_count": 46,
                "coverage_start": first_ts,
                "coverage_end": last_ts,
                "sha256": sha,
                "source": "binance_public_klines",
                "data_ok": True,
            }
        ],
    }


def _recent_window(days: int = 40) -> tuple[int, int]:
    last = int((NOW - timedelta(days=1)).timestamp())
    first = int((NOW - timedelta(days=days)).timestamp())
    return first, last


def _write_manifest(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _run(targets, cache_root, **kwargs):
    kwargs.setdefault("fetcher", _exploding_fetcher)
    kwargs.setdefault("now", NOW)
    kwargs.setdefault("coverage_days_override", 45)
    return reseed(targets, cache_root=cache_root, **kwargs)


# --------------------------------------------------------------------------
# Lecture des manifests
# --------------------------------------------------------------------------


def test_manifest_basename_ignore_les_chemins_absolus_windows():
    # Le defaut corrige : les manifests portent des chemins de la machine
    # d'origine, inexploitables tels quels (et non decoupes par Path().name
    # sous POSIX).
    raw = WINDOWS_PATH_PREFIX + "ohlc_daily_BTC.json"
    assert manifest_basename(raw) == "ohlc_daily_BTC.json"
    assert manifest_basename("/home/x/data/collector_cache/funding_ETH.json") == (
        "funding_ETH.json"
    )
    assert manifest_basename("") == ""


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ohlc_daily_BTC.json", ("ohlcv", "1d")),
        ("ohlc_4h_ETH.json", ("ohlcv", "4h")),
        ("ohlc_1h_SOL.json", ("ohlcv", "1h")),
        ("funding_BTC.json", ("funding", None)),
        ("oi_BTC_4h.json", ("open_interest", "4h")),
        ("basis_ETH_4h.json", ("basis", "4h")),
        ("decisions.jsonl", None),
    ],
)
def test_classify_filename(name, expected):
    assert classify_filename(name) == expected


def test_target_depuis_manifest_pointe_dans_le_cache_local(tmp_path):
    first_ts, last_ts = _recent_window()
    manifest = _write_manifest(
        tmp_path, "data_quality.json", _phase24_manifest("ab" * 32, first_ts=first_ts, last_ts=last_ts)
    )
    targets = load_targets([manifest])
    assert len(targets) == 1
    target = targets[0]
    assert target.kind == "ohlcv"
    assert target.asset == "BTC"
    assert target.timeframe == "1d"
    assert target.filename == "ohlc_daily_BTC.json"
    assert target.sha256 == "ab" * 32
    assert target.row_count == 46
    assert target.first_timestamp == first_ts


def test_meme_cache_cite_par_deux_manifests_est_dedoublonne(tmp_path):
    first_ts, last_ts = _recent_window()
    sha = "cd" * 32
    m21 = _write_manifest(
        tmp_path, "ohlcv_backbone_manifest.json",
        _phase21_manifest(sha, first_ts=first_ts, last_ts=last_ts),
    )
    m24 = _write_manifest(
        tmp_path, "data_quality.json",
        _phase24_manifest(sha, first_ts=first_ts, last_ts=last_ts),
    )
    targets = load_targets([m21, m24])
    assert len(targets) == 1
    assert sorted(targets[0].sources) == ["data_quality.json", "ohlcv_backbone_manifest.json"]


def test_sha256_divergent_entre_manifests_est_signale():
    first_ts, _ = _recent_window()
    a = parse_manifest_payload(
        _phase21_manifest("11" * 32, first_ts=first_ts, last_ts=first_ts + 86400),
        source="m21",
    )
    b = parse_manifest_payload(
        _phase24_manifest("22" * 32, first_ts=first_ts, last_ts=first_ts + 86400),
        source="m24",
    )
    merged = merge_targets(a + b)
    assert len(merged) == 1
    assert any("sha256 divergent" in w for w in merged[0].warnings)


def test_series_non_collectee_et_liquidations_sont_ignorees():
    payload = {
        "entries": [
            {
                "asset": "SOL",
                "series": "funding",
                "path": WINDOWS_PATH_PREFIX + "funding_SOL.json",
                "status": "blocked_data",
                "row_count": 0,
                "blocked_reason": "cache file missing",
            },
            {
                "asset": "*",
                "series": "liquidations",
                "path": "",
                "status": "blocked_data",
                "row_count": 0,
            },
        ]
    }
    targets = merge_targets(parse_manifest_payload(payload, source="phase26"))
    assert {t.filename for t in targets} == {"funding_SOL.json", "liquidations"}
    assert all(t.skip_reason for t in targets)


def test_sous_sections_de_derivatives_depth_sont_lues():
    payload = {
        "oi_depth": {
            "entries": [
                {
                    "asset": "BTC",
                    "period": "4h",
                    "path": WINDOWS_PATH_PREFIX + "oi_BTC_4h.json",
                    "row_count": 180,
                    "gate_status": "available",
                }
            ]
        },
        "basis": {
            "timeframe": "4h",
            "entries": [
                {
                    "asset": "ETH",
                    "series": "basis_4h",
                    "path": WINDOWS_PATH_PREFIX + "basis_ETH_4h.json",
                    "status": "available",
                    "row_count": 6603,
                }
            ],
        },
    }
    targets = merge_targets(parse_manifest_payload(payload, source="depth.json"))
    assert {(t.kind, t.filename) for t in targets} == {
        ("open_interest", "oi_BTC_4h.json"),
        ("basis", "basis_ETH_4h.json"),
    }


def test_entree_sans_chemin_retombe_sur_le_nom_canonique():
    payload = {
        "entries": [
            {"asset": "BTC", "series": "basis_4h", "path": "", "status": "available",
             "row_count": 500}
        ]
    }
    targets = merge_targets(parse_manifest_payload(payload, source="x"))
    assert targets[0].filename == "basis_BTC_4h.json"


def test_les_manifests_versionnes_reels_sont_lisibles():
    targets = load_targets(list(DEFAULT_MANIFESTS))
    names = {t.filename for t in targets}
    assert "ohlc_daily_BTC.json" in names
    assert "ohlc_1h_SOL.json" in names
    assert "funding_BTC.json" in names
    assert "oi_ETH_4h.json" in names
    assert "basis_BTC_4h.json" in names
    ohlc_btc = next(t for t in targets if t.filename == "ohlc_daily_BTC.json")
    assert ohlc_btc.sha256 == (
        "2a3799bf39c391c43d76c5a1025e8c90cf34714c685d9d73d5c7be90f2ba979c"
    )
    assert ohlc_btc.row_count == 1831


# --------------------------------------------------------------------------
# Garde-fous d'ecriture
# --------------------------------------------------------------------------


def test_racine_dans_reports_est_refusee():
    with pytest.raises(ReseedError):
        resolve_cache_root(REPO / "reports" / "phase24_data_backbone")
    with pytest.raises(ReseedError):
        resolve_cache_root(REPO / "data")


def test_racine_collector_cache_est_acceptee():
    assert resolve_cache_root(REPO / "data" / "collector_cache").name == "collector_cache"
    sub = resolve_cache_root(REPO / "data" / "collector_cache" / "sub")
    assert sub.name == "sub"


# --------------------------------------------------------------------------
# Reconstruction
# --------------------------------------------------------------------------


def _ohlcv_target(sha: str | None = None) -> CacheTarget:
    first_ts, last_ts = _recent_window()
    return CacheTarget(
        kind="ohlcv",
        asset="BTC",
        filename="ohlc_daily_BTC.json",
        timeframe="1d",
        sha256=sha,
        row_count=46,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        sources=["test"],
    )


def test_dry_run_n_ecrit_rien_et_n_appelle_pas_le_reseau(tmp_path):
    report = _run([_ohlcv_target("ff" * 32)], tmp_path, dry_run=True)
    assert report["results"][0]["status"] == STATUS_ABSENT
    assert report["results"][0]["action"] == "would_fetch"
    assert list(tmp_path.iterdir()) == []


def test_dry_run_sur_cache_absent_sort_2_et_pas_0(tmp_path):
    # Defaut corrige : exit_code_for renvoyait 0 des que dry_run etait vrai,
    # donc `--dry-run` sortait 0 avec les 17 caches manquants et ne pouvait pas
    # servir de controle CI (« les caches attendus sont-ils la ? »).
    report = _run([_ohlcv_target("ff" * 32)], tmp_path, dry_run=True)
    assert report["dry_run"] is True
    assert report["counts"] == {STATUS_ABSENT: 1}
    assert exit_code_for(report) == 2


def test_dry_run_sans_rien_a_faire_sort_0(tmp_path):
    # Symetrique du test precedent : le code 2 doit rester un signal, pas un
    # « toujours 2 » qui remplacerait le « toujours 0 ».
    fake = FakeBinance()
    _run([_ohlcv_target(None)], tmp_path, fetcher=fake)
    real_sha = sha256_file(tmp_path / "ohlc_daily_BTC.json")

    report = _run([_ohlcv_target(real_sha)], tmp_path, dry_run=True)
    assert report["results"][0]["status"] == STATUS_MATCH
    assert exit_code_for(report) == 0


def test_cache_absent_est_reconstruit_et_le_sha_est_rapporte(tmp_path):
    fake = FakeBinance()
    report = _run([_ohlcv_target("ff" * 32)], tmp_path, fetcher=fake)
    result = report["results"][0]
    assert result["status"] == STATUS_REBUILT
    path = tmp_path / "ohlc_daily_BTC.json"
    assert path.is_file()
    assert result["sha256_actual"] == sha256_file(path)
    assert result["sha256_actual"] != "ff" * 32
    assert result["row_count_actual"] >= 46
    # L'horodatage embarque rend la reproduction octet-a-octet impossible :
    # l'outil doit le dire au lieu de laisser croire a une corruption.
    assert "octet-a-octet" in result["note"]
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["ticker"] == "BTC"
    assert payload["interval_minutes"] == 1440
    assert len(payload["entries"]["candles"]) == result["row_count_actual"]
    assert not list(tmp_path.glob("*.reseed-tmp"))


def test_cache_conforme_est_laisse_intact(tmp_path):
    fake = FakeBinance()
    _run([_ohlcv_target(None)], tmp_path, fetcher=fake)
    path = tmp_path / "ohlc_daily_BTC.json"
    before = path.read_bytes()
    real_sha = sha256_file(path)

    report = _run([_ohlcv_target(real_sha)], tmp_path, fetcher=_exploding_fetcher)
    assert report["results"][0]["status"] == STATUS_MATCH
    assert path.read_bytes() == before
    assert exit_code_for(report) == 0


def test_cache_divergent_n_est_jamais_ecrase_silencieusement(tmp_path):
    path = tmp_path / "ohlc_daily_BTC.json"
    path.write_text('{"source": "cache local a moi"}', encoding="utf-8")
    before = path.read_bytes()

    report = _run([_ohlcv_target("ab" * 32)], tmp_path, fetcher=_exploding_fetcher)
    result = report["results"][0]
    assert result["status"] == STATUS_MISMATCH
    assert path.read_bytes() == before, "le cache local a ete ecrase sans --force"
    assert "non ecrase" in result["note"]
    assert exit_code_for(report) == 2


def test_force_reconstruit_le_cache_divergent(tmp_path):
    path = tmp_path / "ohlc_daily_BTC.json"
    path.write_text('{"source": "cache local a moi"}', encoding="utf-8")
    fake = FakeBinance()

    report = _run([_ohlcv_target("ab" * 32)], tmp_path, fetcher=fake, force=True)
    assert report["results"][0]["status"] == STATUS_REBUILT
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["entries"]["candles"]


# --------------------------------------------------------------------------
# Cibles sans sha256 dans le manifest (8 des 17 : funding, OI, basis)
# --------------------------------------------------------------------------


def _oi_target(row_count: int = 180) -> CacheTarget:
    """Cible telle que la produisent les manifests phase 26/27 : aucun sha256."""
    return CacheTarget(
        kind="open_interest",
        asset="BTC",
        filename="oi_BTC_4h.json",
        timeframe="4h",
        sha256=None,
        row_count=row_count,
        sources=["derivatives_readiness.json"],
    )


def _write_oi_cache(path: Path, *, rows: int) -> None:
    """Cache OI plausible, ecrit par le collector du depot (pas de schema invente)."""
    end = int(NOW.timestamp())
    save_oi_cache(
        path,
        ticker="BTC",
        period="4h",
        rows=[
            {
                "symbol": "BTCUSDT",
                "timestamp": (end - i * 14_400) * 1000,
                "sumOpenInterest": f"{70000 + i}",
                "sumOpenInterestValue": f"{70000 + i}00",
            }
            for i in range(rows)
        ],
    )


def test_cache_sans_sha256_coherent_est_present_unverified_pas_match(tmp_path):
    # Defaut corrige : absence de sha256 dans le manifest => statut "match"
    # rendu sans ouvrir le fichier. Le statut doit dire ce qui est vrai :
    # present et coherent, mais identite non prouvable.
    path = tmp_path / "oi_BTC_4h.json"
    _write_oi_cache(path, rows=180)
    before = path.read_bytes()

    report = _run([_oi_target()], tmp_path, fetcher=_exploding_fetcher)
    result = report["results"][0]
    assert result["status"] == STATUS_PRESENT_UNVERIFIED
    assert result["status"] != STATUS_MATCH
    assert result["row_count_actual"] == 180
    assert result["first_timestamp_actual"] is not None
    assert result["last_timestamp_actual"] is not None
    assert path.read_bytes() == before
    assert exit_code_for(report) == 0


def test_cache_sans_sha256_illisible_est_une_divergence(tmp_path):
    # Le cas empirique du relecteur : 17 octets de JSON sans rapport rapportes
    # "match", row_count_actual null, exit 0.
    path = tmp_path / "oi_BTC_4h.json"
    path.write_text('{"garbage": true}', encoding="utf-8")
    before = path.read_bytes()

    report = _run([_oi_target()], tmp_path, fetcher=_exploding_fetcher)
    result = report["results"][0]
    assert result["status"] == STATUS_MISMATCH
    assert result["row_count_actual"] is None
    assert "structure inconnue" in result["note"]
    assert path.read_bytes() == before, "un cache non verifiable ne s'ecrase pas seul"
    assert exit_code_for(report) == 2


def test_cache_sans_sha256_tronque_est_une_divergence(tmp_path):
    # Fichier de forme valide mais 20 lignes au lieu des 180 du manifest.
    path = tmp_path / "oi_BTC_4h.json"
    _write_oi_cache(path, rows=20)

    report = _run([_oi_target(180)], tmp_path, fetcher=_exploding_fetcher)
    result = report["results"][0]
    assert result["status"] == STATUS_MISMATCH
    assert result["row_count_actual"] == 20
    assert "row_count 20 < 180" in result["note"]
    assert exit_code_for(report) == 2


def test_cache_sans_sha256_dont_la_fenetre_demarre_trop_tard_diverge(tmp_path):
    # Bon nombre de lignes, mais la serie ne remonte pas aussi loin que le
    # manifest : c'est une autre fenetre, pas le cache des phases 21-30.
    first_ts, last_ts = _recent_window(days=40)
    target = CacheTarget(
        kind="ohlcv",
        asset="BTC",
        filename="ohlc_daily_BTC.json",
        timeframe="1d",
        sha256=None,
        row_count=10,
        first_timestamp=first_ts,
        last_timestamp=last_ts,
        sources=["test"],
    )
    save_ohlc_cache(
        tmp_path / "ohlc_daily_BTC.json",
        ticker="BTC",
        timeframe="1d",
        rows=[
            {
                "timestamp": first_ts + (20 + i) * 86_400,
                "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 3.0,
            }
            for i in range(10)
        ],
    )

    report = _run([target], tmp_path, fetcher=_exploding_fetcher)
    result = report["results"][0]
    assert result["status"] == STATUS_MISMATCH
    assert "posterieur au manifest" in result["note"]
    assert exit_code_for(report) == 2


def test_force_reconstruit_un_cache_sans_sha256_dans_le_manifest(tmp_path):
    # Defaut corrige : le retour anticipe "pas de sha256 => match" se faisait
    # AVANT le test de --force, donc --force ne reconstruisait jamais l'open
    # interest — pourtant la serie la plus perimee par construction.
    path = tmp_path / "oi_BTC_4h.json"
    path.write_text('{"garbage": true}', encoding="utf-8")
    fake = FakeBinance()

    # row_count aligne sur ce que rend la fixture (40 lignes) : la verification
    # post-reconstruction est ainsi exercee sur son chemin nominal, et non
    # court-circuitee par une divergence de volume attendue.
    report = _run([_oi_target(40)], tmp_path, fetcher=fake, force=True)
    result = report["results"][0]
    assert result["status"] == STATUS_REBUILT
    assert result["action"] == "fetch"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["kind"] == "open_interest"
    assert payload["entries"]["rows"], "le cache poubelle n'a pas ete remplace"
    assert "https://fapi.binance.com/futures/data/openInterestHist" in {
        url for url, _ in fake.calls
    }


def test_force_ne_detruit_pas_un_cache_dont_le_sha_est_celui_du_manifest(tmp_path):
    # Contrepartie : un fichier identique au manifest est l'original exact,
    # irrecuperable une fois ecrase. --force ne doit pas le re-fetcher.
    fake = FakeBinance()
    _run([_ohlcv_target(None)], tmp_path, fetcher=fake)
    path = tmp_path / "ohlc_daily_BTC.json"
    before = path.read_bytes()

    report = _run(
        [_ohlcv_target(sha256_file(path))],
        tmp_path,
        fetcher=_exploding_fetcher,
        force=True,
    )
    assert report["results"][0]["status"] == STATUS_MATCH
    assert path.read_bytes() == before


# --------------------------------------------------------------------------
# Volume du cache reconstruit
# --------------------------------------------------------------------------


def test_reconstruction_trop_courte_est_signalee_et_sort_2(tmp_path):
    # Defaut corrige : row_count_actual n'etait jamais compare a
    # row_count_expected apres 'rebuilt'. Comme l'outil passe toujours
    # coverage_days explicitement, le plancher MIN_ROWS_DATA_OK du collector
    # est desactive : un ohlc_1h reconstruit trop court sortait 'rebuilt' + 0.
    target = CacheTarget(
        kind="ohlcv",
        asset="BTC",
        filename="ohlc_1h_BTC.json",
        timeframe="1h",
        sha256=None,
        row_count=17_650,  # valeur du manifest phase 21
        sources=["ohlcv_backbone_manifest.json"],
    )
    fake = FakeBinance()
    report = _run([target], tmp_path, fetcher=fake, coverage_days_override=45)
    result = report["results"][0]

    assert (tmp_path / "ohlc_1h_BTC.json").is_file(), "le fetch a bien eu lieu"
    assert result["row_count_actual"] < 17_650
    assert result["status"] == STATUS_MISMATCH
    assert "reconstruit mais divergent" in result["note"]
    assert exit_code_for(report) == 2


def test_reconstruction_au_volume_attendu_reste_rebuilt(tmp_path):
    # Sans ce test, "toujours mismatch" passerait aussi le test precedent.
    target = CacheTarget(
        kind="ohlcv",
        asset="BTC",
        filename="ohlc_1h_BTC.json",
        timeframe="1h",
        sha256=None,
        row_count=1_000,
        sources=["t"],
    )
    report = _run([target], tmp_path, fetcher=FakeBinance(), coverage_days_override=45)
    result = report["results"][0]
    assert result["status"] == STATUS_REBUILT
    assert result["row_count_actual"] >= 1_000
    assert exit_code_for(report) == 0


def test_tolerance_de_row_count_absorbe_la_bougie_de_bord():
    target = CacheTarget(kind="ohlcv", asset="BTC", filename="x.json", row_count=1000)
    assert content_divergences(target, {"row_count": 999}) == []
    assert content_divergences(target, {"row_count": 979})  # -2.1 % : trop


def test_inspect_cache_file_lit_les_deux_dispositions_de_lignes(tmp_path):
    ohlc = tmp_path / "ohlc_daily_BTC.json"
    save_ohlc_cache(
        ohlc,
        ticker="BTC",
        timeframe="1d",
        rows=[{"timestamp": 1_700_000_000 + i * 86_400} for i in range(3)],
    )
    assert inspect_cache_file(ohlc)["row_count"] == 3
    assert inspect_cache_file(ohlc)["first_timestamp"] == 1_700_000_000

    oi = tmp_path / "oi_BTC_4h.json"
    _write_oi_cache(oi, rows=5)
    assert inspect_cache_file(oi)["row_count"] == 5

    broken = tmp_path / "broken.json"
    broken.write_text("pas du json", encoding="utf-8")
    assert inspect_cache_file(broken)["unreadable"]
    assert inspect_cache_file(tmp_path / "jamais_ecrit.json")["unreadable"]


# --------------------------------------------------------------------------
# Profondeur de fetch
# --------------------------------------------------------------------------


def test_coverage_days_for_couvre_la_fenetre_du_manifest():
    # Non couvert jusqu'ici : le helper _run force coverage_days_override=45,
    # donc coverage_days_for n'etait jamais exerce.
    #
    # Contrat reel : la profondeur couvre la fenetre du manifest ET reste au
    # moins egale a la profondeur par defaut du collector. Le defaut est un
    # PLANCHER, pas une cible : re-fetcher moins profond que le collector
    # produirait un cache qui echouerait le gate data_ok de la phase 21.
    old = CacheTarget(
        kind="ohlcv", asset="BTC", filename="ohlc_daily_BTC.json", timeframe="1d",
        first_timestamp=int((NOW - timedelta(days=400)).timestamp()),
    )
    default_1d = TIMEFRAME_COVERAGE_DAYS["1d"]
    assert coverage_days_for(old, now=NOW) == max(405, default_1d)

    # Fenetre plus large que le defaut : c'est elle qui commande.
    ancient = CacheTarget(
        kind="ohlcv", asset="BTC", filename="ohlc_daily_BTC.json", timeframe="1d",
        first_timestamp=int((NOW - timedelta(days=default_1d + 300)).timestamp()),
    )
    assert coverage_days_for(ancient, now=NOW) == default_1d + 305

    # Sans borne de debut dans le manifest, on retombe sur le defaut.
    unknown = CacheTarget(
        kind="ohlcv", asset="BTC", filename="ohlc_daily_BTC.json", timeframe="1d"
    )
    assert coverage_days_for(unknown, now=NOW) == default_1d

    # Fenetre courte : on ne descend pas sous la profondeur par defaut du
    # timeframe, sinon le collector rendrait moins de barres qu'attendu.
    recent = CacheTarget(
        kind="ohlcv", asset="BTC", filename="ohlc_1h_BTC.json", timeframe="1h",
        first_timestamp=int((NOW - timedelta(days=3)).timestamp()),
    )
    assert coverage_days_for(recent, now=NOW) == TIMEFRAME_COVERAGE_DAYS["1h"]

    # Aucune borne dans le manifest (cas des manifests derivatives).
    blind = CacheTarget(
        kind="ohlcv", asset="BTC", filename="ohlc_4h_BTC.json", timeframe="4h"
    )
    assert coverage_days_for(blind, now=NOW) == TIMEFRAME_COVERAGE_DAYS["4h"]

    unknown = CacheTarget(kind="funding", asset="BTC", filename="funding_BTC.json")
    assert coverage_days_for(unknown, now=NOW) is None


def test_la_profondeur_de_fetch_remonte_avant_la_premiere_barre_du_manifest(tmp_path):
    first_ts = int((NOW - timedelta(days=300)).timestamp())
    target = CacheTarget(
        kind="ohlcv", asset="BTC", filename="ohlc_daily_BTC.json", timeframe="1d",
        row_count=10, first_timestamp=first_ts, sources=["t"],
    )
    fake = FakeBinance()
    # Pas de coverage_days_override : c'est coverage_days_for qui decide.
    reseed([target], cache_root=tmp_path, fetcher=fake, now=NOW)

    starts = [int(p["startTime"]) for _, p in fake.calls if "startTime" in p]
    assert starts, "aucun appel klines"
    assert min(starts) <= first_ts * 1000, "la fenetre fetchee rate le debut du manifest"


def test_cible_ignoree_n_appelle_pas_le_collector(tmp_path):
    target = CacheTarget(
        kind="funding",
        asset="SOL",
        filename="funding_SOL.json",
        sources=["phase26"],
        skip_reason="jamais collecte a l'origine (cache file missing)",
    )
    report = _run([target], tmp_path, fetcher=_exploding_fetcher)
    assert report["results"][0]["status"] == STATUS_SKIPPED
    assert not (tmp_path / "funding_SOL.json").exists()


def test_funding_oi_et_basis_passent_par_les_collectors_du_depot(tmp_path):
    fake = FakeBinance()
    # row_count aligne sur ce que le faux Binance produit : ce test verifie le
    # routage vers les collectors, pas le controle de volume (teste plus bas).
    targets = [
        CacheTarget(kind="funding", asset="BTC", filename="funding_BTC.json",
                    row_count=120, sources=["t"]),
        CacheTarget(kind="open_interest", asset="BTC", filename="oi_BTC_4h.json",
                    timeframe="4h", row_count=40, sources=["t"]),
        CacheTarget(kind="basis", asset="ETH", filename="basis_ETH_4h.json",
                    timeframe="4h", row_count=270, sources=["t"]),
    ]
    report = _run(targets, tmp_path, fetcher=fake)
    assert [r["status"] for r in report["results"]] == [STATUS_REBUILT] * 3

    funding = json.loads((tmp_path / "funding_BTC.json").read_text(encoding="utf-8"))
    assert funding["kind"] == "funding"
    assert funding["symbol"] == "BTCUSDT"
    assert len(funding["entries"]["rows"]) == 120

    oi = json.loads((tmp_path / "oi_BTC_4h.json").read_text(encoding="utf-8"))
    assert oi["kind"] == "open_interest"
    assert oi["period"] == "4h"

    basis = json.loads((tmp_path / "basis_ETH_4h.json").read_text(encoding="utf-8"))
    assert basis["kind"] == "basis"
    row = basis["entries"]["rows"][0]
    assert {"spot_price", "perp_price", "basis_pct"} <= set(row)

    urls = {url for url, _ in fake.calls}
    assert "https://fapi.binance.com/fapi/v1/fundingRate" in urls
    assert "https://fapi.binance.com/futures/data/openInterestHist" in urls
    assert "https://fapi.binance.com/fapi/v1/markPriceKlines" in urls


def test_echec_de_fetch_est_rapporte_sans_laisser_de_fichier_partiel(tmp_path):
    def boom(url, params=None):
        raise RuntimeError("HTTP 451 geo-block")

    report = _run([_ohlcv_target("ab" * 32)], tmp_path, fetcher=boom)
    result = report["results"][0]
    assert result["status"] == STATUS_ERROR
    assert "HTTP 451" in result["note"]
    assert list(tmp_path.iterdir()) == []
    assert exit_code_for(report) == 1


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def test_cli_dry_run_hors_ligne_sur_les_manifests_reels(tmp_path):
    cache_root = tmp_path / "collector_cache"
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "reseed_collector_cache.py"),
            "--dry-run",
            "--json",
            "--cache-root",
            str(cache_root),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    # Racine vide => tous les caches sont absents => code 2 ("cache toujours
    # absent"), pas 0. C'est ce qui rend `--dry-run` utilisable en CI.
    assert proc.returncode == 2, proc.stderr
    report = json.loads(proc.stdout)
    assert report["dry_run"] is True
    assert report["targets_total"] >= 20
    names = {r["filename"] for r in report["results"]}
    assert "ohlc_daily_BTC.json" in names
    assert not cache_root.exists(), "le dry-run ne doit rien creer"


def test_cli_refuse_d_ecrire_dans_reports(tmp_path):
    # ``--dry-run`` en plus du garde-fou : si un jour la garde saute, ce test
    # doit echouer sans avoir pu deposer un seul octet dans reports/.
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "reseed_collector_cache.py"),
            "--dry-run",
            "--cache-root",
            str(REPO / "reports" / "data_manifests_phase21"),
            "--only",
            "BTC",
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 1
    assert "racine de cache interdite" in proc.stderr


def test_cli_only_filtre_les_actifs(tmp_path):
    proc = subprocess.run(
        [
            PY,
            str(REPO / "scripts" / "reseed_collector_cache.py"),
            "--dry-run",
            "--json",
            "--only",
            "ETH",
            "--cache-root",
            str(tmp_path / "cache"),
        ],
        capture_output=True,
        text=True,
        cwd=REPO,
        check=False,
    )
    assert proc.returncode == 2, proc.stderr  # caches absents sous tmp_path
    report = json.loads(proc.stdout)
    assert report["results"]
    assert {r["asset"] for r in report["results"]} == {"ETH"}
