"""Phase 26A — derivatives collectors (no network)."""

from __future__ import annotations

from pathlib import Path

from src.data.collectors.binance_derivatives_public import (
    LIQUIDATIONS_STATUS,
    audit_derivatives_readiness,
    default_funding_cache_path,
    default_oi_cache_path,
    fetch_funding_rate_history,
    load_derivatives_cache,
    parse_funding_rows,
    save_funding_cache,
    save_oi_cache,
)


def _fake_fetcher(url: str, params: dict) -> list:
    if "fundingRate" in url:
        # Single page (< limit) to avoid pagination loop in tests.
        return [
            {
                "symbol": params["symbol"],
                "fundingRate": "0.0001",
                "fundingTime": 1_700_000_000_000,
            },
        ]
    return [
        {
            "symbol": params["symbol"],
            "sumOpenInterest": "1000.5",
            "timestamp": 1_700_000_000_000,
        }
    ]


def test_parse_funding_rows_dedupes() -> None:
    rows = parse_funding_rows(
        [
            {"fundingTime": 1000, "fundingRate": "0.01"},
            {"fundingTime": 1000, "fundingRate": "0.02"},
            {"fundingTime": 2000, "fundingRate": "-0.01"},
        ]
    )
    assert len(rows) == 2
    assert rows[0]["timestamp"] == 1000


def test_fetch_funding_hermetic(tmp_path: Path) -> None:
    rows = fetch_funding_rate_history("BTC", fetcher=_fake_fetcher)
    assert len(rows) >= 1
    assert "funding_rate" in rows[0]


def test_save_load_funding_cache(tmp_path: Path) -> None:
    path = tmp_path / "funding_BTC.json"
    save_funding_cache(
        path,
        ticker="BTC",
        rows=[{"fundingTime": 1700000000, "fundingRate": "0.0001"}],
    )
    loaded, meta = load_derivatives_cache(path)
    assert len(loaded) == 1
    assert meta.get("status") == "available"


def test_save_load_oi_cache(tmp_path: Path) -> None:
    path = tmp_path / "oi_ETH_4h.json"
    save_oi_cache(
        path,
        ticker="ETH",
        period="4h",
        rows=[{"timestamp": 1700000000, "sumOpenInterest": "500"}],
    )
    loaded, _ = load_derivatives_cache(path)
    assert loaded[0]["open_interest"] == 500.0


def test_audit_readiness_blocked_without_cache(tmp_path: Path) -> None:
    manifest = audit_derivatives_readiness(["BTC"], cache_dir=tmp_path, min_funding_rows=10)
    liq = next(e for e in manifest["entries"] if e["series"] == "liquidations")
    assert liq["status"] == LIQUIDATIONS_STATUS


def test_audit_readiness_ok_with_seed(tmp_path: Path) -> None:
    save_funding_cache(
        default_funding_cache_path("BTC", tmp_path),
        ticker="BTC",
        rows=[
            {"fundingTime": 1_600_000_000 + i * 28800, "fundingRate": "0.0001"}
            for i in range(120)
        ],
    )
    save_oi_cache(
        default_oi_cache_path("BTC", "4h", tmp_path),
        ticker="BTC",
        period="4h",
        rows=[
            {"timestamp": 1_600_000_000 + i * 14400, "sumOpenInterest": str(1000 + i)}
            for i in range(120)
        ],
    )
    manifest = audit_derivatives_readiness(["BTC"], cache_dir=tmp_path, min_funding_rows=100)
    funding = next(e for e in manifest["entries"] if e["series"] == "funding")
    assert funding["status"] == "available"


# --- Defaut #4: pagination du funding tronquee a une page -------------------

FUNDING_T0_MS = 1_600_000_000_000
FUNDING_STEP_MS = 8 * 3600 * 1000


def _binance_like_funding_fetcher(
    timestamps: list[int],
    page_limit: int,
    calls: list[dict],
):
    """Imite ``/fapi/v1/fundingRate``: ordre croissant depuis ``startTime``.

    C'est ce comportement (et non "newest page first") qui faisait sortir
    l'ancienne boucle des la premiere page.
    """
    state: dict[str, int | None] = {"last": None}

    def fetcher(url: str, params: dict) -> list:
        calls.append(dict(params))
        start = int(params.get("startTime", 0))
        end = params.get("endTime")
        selected = [
            t
            for t in timestamps
            if t >= start and (end is None or t <= int(end))
        ]
        page = selected[:page_limit]
        rows = [
            {
                "symbol": params["symbol"],
                "fundingRate": f"{(i + 1) * 1e-5:.8f}",
                "fundingTime": t,
            }
            for i, t in enumerate(page)
        ]
        if state["last"] is not None:
            # Doublon inter-pages: le serveur peut renvoyer un point deja vu.
            rows.append(
                {
                    "symbol": params["symbol"],
                    "fundingRate": "0.00001",
                    "fundingTime": state["last"],
                }
            )
        if page:
            state["last"] = page[-1]
        # L'ordre de page n'est pas garanti: on force l'ordre inverse.
        return list(reversed(rows))

    return fetcher


def test_fetch_funding_paginates_beyond_first_page(monkeypatch) -> None:
    """3 pages -> 3 pages concatenees, dedupliquees et triees."""
    import src.data.collectors.binance_derivatives_public as mod

    monkeypatch.setattr(mod, "FUNDING_PAGE_LIMIT", 5)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    timestamps = [FUNDING_T0_MS + i * FUNDING_STEP_MS for i in range(12)]
    calls: list[dict] = []
    fetcher = _binance_like_funding_fetcher(timestamps, 5, calls)

    rows = mod.fetch_funding_rate_history(
        "ETH",
        start_ms=timestamps[0],
        end_ms=timestamps[-1] + 1,
        fetcher=fetcher,
    )

    # Pages de 5 + 5 + 2: sans la correction on s'arretait a 5 lignes.
    assert len(calls) == 3
    assert len(rows) == 12
    got = [int(r["timestamp"]) for r in rows]
    assert got == sorted(got)
    assert len(set(got)) == len(got)
    assert got[0] == timestamps[0] // 1000
    assert got[-1] == timestamps[-1] // 1000


def test_fetch_funding_advances_start_time(monkeypatch) -> None:
    """Le curseur avance sur startTime, il ne recule pas sur endTime."""
    import src.data.collectors.binance_derivatives_public as mod

    monkeypatch.setattr(mod, "FUNDING_PAGE_LIMIT", 5)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    timestamps = [FUNDING_T0_MS + i * FUNDING_STEP_MS for i in range(12)]
    calls: list[dict] = []
    fetcher = _binance_like_funding_fetcher(timestamps, 5, calls)
    mod.fetch_funding_rate_history(
        "ETH", start_ms=timestamps[0], end_ms=timestamps[-1] + 1, fetcher=fetcher
    )

    starts = [int(c["startTime"]) for c in calls]
    assert starts == sorted(starts)
    assert starts[1] > starts[0]
    assert all(int(c["endTime"]) == timestamps[-1] + 1 for c in calls)


def test_pagination_truncation_warning_flags_exact_multiple() -> None:
    from src.data.collectors.binance_derivatives_public import (
        pagination_truncation_warning,
    )

    warn = pagination_truncation_warning(1000, page_limit=1000, last_page_full=True)
    assert warn is not None
    assert "1000" in warn

    # Page finale incomplete = fin normale de l'historique.
    assert pagination_truncation_warning(1000, page_limit=1000, last_page_full=False) is None
    # Total non multiple = rien d'anormal.
    assert pagination_truncation_warning(1007, page_limit=1000, last_page_full=True) is None
    assert pagination_truncation_warning(0, page_limit=1000, last_page_full=True) is None


def test_fetch_funding_warns_when_pagination_stalls(monkeypatch) -> None:
    """Un curseur bloque sur une page pleine doit crier, pas se taire."""
    import src.data.collectors.binance_derivatives_public as mod

    monkeypatch.setattr(mod, "FUNDING_PAGE_LIMIT", 5)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)

    def stuck_fetcher(url: str, params: dict) -> list:
        # Ignore startTime: renvoie toujours la meme page pleine.
        return [
            {
                "symbol": params["symbol"],
                "fundingRate": "0.0001",
                "fundingTime": FUNDING_T0_MS + i * FUNDING_STEP_MS,
            }
            for i in range(5)
        ]

    seen: list[str] = []
    monkeypatch.setattr(mod.logger, "warning", lambda fmt, *a: seen.append(fmt % a))

    rows = mod.fetch_funding_rate_history(
        "ETH", start_ms=FUNDING_T0_MS, end_ms=None, fetcher=stuck_fetcher
    )
    assert len(rows) == 5
    assert seen
    assert "likely truncated" in seen[0]
