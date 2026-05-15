"""Minimal trading-terminal style dashboard for the Kraken Alpha Agent."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import kraken_cli, storage
from ..config import PROJECT_ROOT, get_settings, safe_env_snapshot
from ..logger import get_logger
from ..pnl import compute_pnl
from ..portfolio import get_snapshot
from ..utils import fmt_money, utc_now_iso

logger = get_logger(__name__)

_RANKING_CACHE: dict[str, Any] = {"loaded_at": 0.0, "payload": None, "source": "none"}

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))
TEMPLATES.env.filters["fmt_money"] = fmt_money

app = FastAPI(title="Kraken Sentinel — Alpha Agent", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def _decode_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}


def _pnl_source_label() -> str:
    settings = get_settings()
    mode = (settings.env.trading_mode or "dry_run").lower()
    if mode == "live":
        return "live"
    if mode == "paper":
        return "paper"
    return "local_estimate"


def _paper_initialised() -> bool:
    try:
        status = kraken_cli.fetch_paper_status()
    except Exception:  # noqa: BLE001
        return False
    if not isinstance(status, dict):
        return False
    if status.get("using_mock"):
        return False
    data = status.get("data") or {}
    if not isinstance(data, dict):
        return False
    return any(k in data for k in ("balance", "balances", "cash", "equity"))


def _load_latest_ranking(force: bool = False) -> dict[str, Any]:
    """Cached read of the most recent xstocks_rank_*.json file (60s TTL)."""
    settings = get_settings()
    ttl = max(15, settings.config.universe.ranking_cache_seconds or 60)
    if not force and (time.time() - _RANKING_CACHE["loaded_at"]) < ttl and _RANKING_CACHE["payload"] is not None:
        return _RANKING_CACHE["payload"]

    data_dir = PROJECT_ROOT / "data"
    latest = data_dir / "xstocks_rank_latest.json"
    if latest.exists():
        try:
            payload = json.loads(latest.read_text(encoding="utf-8"))
            _RANKING_CACHE["payload"] = payload
            _RANKING_CACHE["loaded_at"] = time.time()
            _RANKING_CACHE["source"] = "file"
            return payload
        except Exception as exc:  # noqa: BLE001
            logger.warning("failed to parse %s: %s", latest, exc)

    # Fallback: pick the newest timestamped file.
    candidates = sorted(data_dir.glob("xstocks_rank_*.json"), reverse=True)
    for candidate in candidates:
        if candidate.name == "xstocks_rank_latest.json":
            continue
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            _RANKING_CACHE["payload"] = payload
            _RANKING_CACHE["loaded_at"] = time.time()
            _RANKING_CACHE["source"] = candidate.name
            return payload
        except Exception:  # noqa: BLE001
            continue

    empty = {"generated_at": None, "profile": None, "count": 0, "rows": []}
    _RANKING_CACHE["payload"] = empty
    _RANKING_CACHE["loaded_at"] = time.time()
    _RANKING_CACHE["source"] = "missing"
    return empty


def _load_latest_backtest() -> dict[str, Any] | None:
    """Load ``data/backtest_latest.json`` if present.

    Returns ``None`` when no backtest has been produced yet so callers can
    render a "no data" UI fragment. Payloads written by the backtester
    always carry ``source = "backtest_local_estimate"`` which we surface
    as-is for transparency.
    """
    data_dir = PROJECT_ROOT / "data"
    latest = data_dir / "backtest_latest.json"
    if not latest.exists():
        return None
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to parse %s: %s", latest, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _load_latest_market_hours() -> dict[str, Any] | None:
    """Load ``data/market_hours_report_latest.json`` if present.

    The payload is always tagged ``source="backtest_local_estimate"`` and
    ``report_kind="market_hours"`` — both are surfaced verbatim so the
    operator can audit provenance.
    """
    data_dir = PROJECT_ROOT / "data"
    latest = data_dir / "market_hours_report_latest.json"
    if not latest.exists():
        return None
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("failed to parse %s: %s", latest, exc)
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _summarise_market_hours(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact market-hours summary used by the HTML view."""
    if not payload:
        return None
    rec = payload.get("recommendation") or {}
    variants = payload.get("variants") or {}
    var_a = variants.get("A_block_low_liquidity") or {}
    var_b = variants.get("B_allow_low_liquidity_simulation_only") or {}
    by_session_a = var_a.get("by_session") or {}
    # Pick the best session by net_pnl_pct in variant A (live-safe).
    best_session = None
    best_pnl = -1e18
    for sess, agg in by_session_a.items():
        if not isinstance(agg, dict):
            continue
        pnl = agg.get("net_pnl_pct") or 0.0
        if pnl > best_pnl:
            best_pnl = pnl
            best_session = sess
    decision = (
        "KEEP_BLOCKING"
        if rec.get("keep_low_liquidity_blocking_in_runtime")
        and not rec.get("allow_in_paper_dry_run_only")
        else (
            "ALLOW_IN_DRY_RUN_ONLY"
            if rec.get("allow_in_paper_dry_run_only")
            else "KEEP_BLOCKING"
        )
    )
    return {
        "timestamp_utc": payload.get("timestamp_utc"),
        "profile": payload.get("profile"),
        "symbols": payload.get("symbols", []),
        "candles_total": payload.get("candles_total", 0),
        "candles_per_session": payload.get("candles_per_session") or {},
        "best_session": best_session,
        "best_session_net_pnl_pct": best_pnl if best_pnl > -1e17 else None,
        "decision": decision,
        "best_window_cest": rec.get("best_window_cest"),
        "best_tickers_for_1530_cest": rec.get("best_tickers_for_1530_cest") or [],
        "rationale": rec.get("rationale"),
        "totals_a": var_a.get("totals") or {},
        "totals_b": var_b.get("totals") or {},
        "comparison": payload.get("comparison") or {},
        "source": payload.get("source", "backtest_local_estimate"),
        "report_kind": payload.get("report_kind", "market_hours"),
    }


def _summarise_backtest(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    """Compact summary used by both the HTML view and the JSON route."""
    if not payload:
        return None
    portfolio = payload.get("portfolio") or {}
    grid = payload.get("grid") or {}
    best_adj = grid.get("best_by_adjusted_score") if isinstance(grid, dict) else None
    cautious = grid.get("cautious_recommendation") if isinstance(grid, dict) else None
    return {
        "generated_at": payload.get("generated_at"),
        "profile": payload.get("profile"),
        "symbols": payload.get("symbols", []),
        "interval_minutes": payload.get("interval_minutes"),
        "net_pnl_pct": portfolio.get("net_pnl_pct"),
        "trades_count": portfolio.get("trades_count"),
        "win_rate": portfolio.get("win_rate"),
        "max_drawdown_pct": portfolio.get("max_drawdown_pct"),
        "buy_count": portfolio.get("buy_count"),
        "sell_count": portfolio.get("sell_count"),
        "hold_count": portfolio.get("hold_count"),
        "best_symbol": portfolio.get("best_symbol"),
        "worst_symbol": portfolio.get("worst_symbol"),
        "best_config": cautious or best_adj,
        "source": payload.get("source", "backtest_local_estimate"),
    }


def _decode_decision_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Decode the JSON blob persisted alongside a decision row."""
    payload = _decode_payload(row.get("payload_json"))
    return payload if isinstance(payload, dict) else {}


def _build_actionability_panel(
    *, decisions: list[dict[str, Any]], ranking: dict[str, Any]
) -> dict[str, Any]:
    """Group recent decisions into BUY / EXIT / NO TRADE buckets.

    ``ranking`` is also consulted: high-opportunity rows that have no
    matching decision yet appear under BUY candidates so the operator can
    see fresh ideas before the next cycle.
    """
    buys: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    no_trade: list[dict[str, Any]] = []
    seen_symbols: set[str] = set()

    for row in decisions:
        payload = _decode_decision_payload(row)
        actionability = payload.get("actionability") if isinstance(payload, dict) else None
        symbol = row.get("symbol")
        if symbol:
            seen_symbols.add(symbol)
        common = {
            "symbol": symbol,
            "action": row.get("action"),
            "score": row.get("final_score"),
            "confidence": row.get("confidence"),
            "approved": row.get("approved"),
            "at": row.get("at"),
            "reason": (actionability or {}).get("reason") if isinstance(actionability, dict) else None,
            "size_dampened": (actionability or {}).get("size_dampened")
            if isinstance(actionability, dict)
            else None,
        }
        if row.get("action") == "BUY" and row.get("approved"):
            buys.append(common)
        elif row.get("action") == "SELL" and row.get("approved"):
            exits.append(common)
        elif row.get("action") == "SELL":
            exits.append(common)
        else:
            # Either HOLD or a blocked trade — surface the rejection reason.
            risk_payload = payload.get("risk") if isinstance(payload, dict) else None
            risk_reasons = []
            if isinstance(risk_payload, dict):
                risk_reasons = list(risk_payload.get("reasons") or [])
            common["risk_reasons"] = risk_reasons
            no_trade.append(common)

    # Ranking rows not yet seen as decisions → additional BUY candidates
    # so the dashboard surfaces fresh ideas during the gap between cycles.
    ranking_rows = (ranking or {}).get("rows") or []
    for r in ranking_rows:
        if not isinstance(r, dict):
            continue
        sym = r.get("symbol")
        if not sym or sym in seen_symbols:
            continue
        opp = r.get("opportunity_score") or 0
        if opp <= 0:
            continue
        buys.append({
            "symbol": sym,
            "action": "BUY_CANDIDATE",
            "score": opp,
            "confidence": r.get("liquidity_score"),
            "approved": False,
            "at": None,
            "reason": "ranking_candidate",
            "size_dampened": None,
        })

    return {
        "buy_candidates": buys[:20],
        "exit_candidates": exits[:20],
        "no_trade": no_trade[:30],
    }


def _common_context() -> dict[str, Any]:
    settings = get_settings()
    portfolio_snap = get_snapshot()
    pnl = compute_pnl(portfolio_snap)
    decisions = storage.fetch_recent_decisions(limit=50)
    orders = storage.fetch_recent_orders(limit=10)
    errors = storage.fetch_recent_errors(limit=5)
    last_decision = decisions[0] if decisions else None
    last_order = orders[0] if orders else None
    env_snap = safe_env_snapshot()
    ranking = _load_latest_ranking()
    pnl_source = _pnl_source_label()
    paper_ok = _paper_initialised() if pnl_source == "paper" else None
    actionability_panel = _build_actionability_panel(decisions=decisions, ranking=ranking)
    backtest_payload = _load_latest_backtest()
    backtest_summary = _summarise_backtest(backtest_payload)
    market_hours_payload = _load_latest_market_hours()
    market_hours_summary = _summarise_market_hours(market_hours_payload)
    return {
        "settings": settings,
        "env_snapshot": env_snap,
        "portfolio": portfolio_snap,
        "pnl": pnl,
        "pnl_source": pnl_source,
        "decisions": decisions[:10],
        "orders": orders,
        "errors": errors,
        "last_decision": last_decision,
        "last_decision_payload": _decode_payload(last_decision.get("payload_json")) if last_decision else None,
        "last_order": last_order,
        "last_order_payload": _decode_payload(last_order.get("payload_json")) if last_order else None,
        "kraken_installed": kraken_cli.is_installed(),
        "kraken_version": kraken_cli.get_version(),
        "alias_public": settings.config.competition.alias_public,
        "agent_codename": settings.config.competition.agent_codename,
        "active_profile": settings.active_profile,
        "available_profiles": settings.available_profiles,
        "ranking": ranking,
        "ranking_source": _RANKING_CACHE.get("source"),
        "no_api_key": not env_snap.get("kraken_api_key_set"),
        "paper_initialised": paper_ok,
        "actionability_panel": actionability_panel,
        "backtest_summary": backtest_summary,
        "market_hours_summary": market_hours_summary,
        "now": utc_now_iso(),
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    ctx = _common_context()
    return TEMPLATES.TemplateResponse(request, "index.html", ctx)


@app.get("/trades", response_class=HTMLResponse)
def trades(request: Request) -> HTMLResponse:
    ctx = _common_context()
    ctx["orders_all"] = storage.fetch_recent_orders(limit=200)
    return TEMPLATES.TemplateResponse(request, "trades.html", ctx)


@app.get("/decisions", response_class=HTMLResponse)
def decisions_page(request: Request) -> HTMLResponse:
    ctx = _common_context()
    ctx["decisions_all"] = storage.fetch_recent_decisions(limit=200)
    return TEMPLATES.TemplateResponse(request, "decisions.html", ctx)


@app.get("/ranking")
def ranking_json() -> JSONResponse:
    payload = _load_latest_ranking()
    return JSONResponse(
        {
            "source": _RANKING_CACHE.get("source"),
            "generated_at": payload.get("generated_at"),
            "profile": payload.get("profile"),
            "count": payload.get("count", 0),
            "rows": payload.get("rows", []),
        }
    )


@app.get("/actionability")
def actionability_json() -> JSONResponse:
    decisions = storage.fetch_recent_decisions(limit=50)
    ranking = _load_latest_ranking()
    return JSONResponse(_build_actionability_panel(decisions=decisions, ranking=ranking))


@app.get("/pnl")
def pnl_json() -> JSONResponse:
    snap = compute_pnl()
    history = storage.fetch_recent_pnl(limit=200)
    return JSONResponse(
        {
            "current": snap.model_dump(mode="json"),
            "history": history,
        }
    )


@app.get("/backtest")
def backtest_json() -> JSONResponse:
    """Return the latest backtest payload, or a sentinel when none exists.

    Strictly read-only: this route never triggers a backtest, it just
    surfaces the JSON file written by ``scripts/backtest_xstocks.py``. The
    payload is always tagged ``source = "backtest_local_estimate"``.
    """
    payload = _load_latest_backtest()
    if payload is None:
        return JSONResponse(
            {
                "status": "no_backtest",
                "message": "Run scripts/backtest_xstocks.py to generate.",
                "source": "backtest_local_estimate",
            }
        )
    return JSONResponse(payload)


@app.get("/market-hours")
def market_hours_json() -> JSONResponse:
    """Return the latest market-hours report, or a sentinel when missing.

    Strictly read-only: this route only surfaces
    ``data/market_hours_report_latest.json`` written by
    ``scripts/backtest_xstocks.py --market-hours-report``. The payload
    always carries ``source="backtest_local_estimate"`` and
    ``report_kind="market_hours"``.
    """
    payload = _load_latest_market_hours()
    if payload is None:
        return JSONResponse(
            {
                "status": "no_market_hours_report",
                "message": (
                    "Run scripts/backtest_xstocks.py --market-hours-report "
                    "to generate."
                ),
                "source": "backtest_local_estimate",
                "report_kind": "market_hours",
            }
        )
    return JSONResponse(payload)


@app.get("/api/decisions")
def api_decisions() -> JSONResponse:
    return JSONResponse({"decisions": storage.fetch_recent_decisions(limit=100)})


@app.get("/api/orders")
def api_orders() -> JSONResponse:
    return JSONResponse({"orders": storage.fetch_recent_orders(limit=100)})


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "kraken_cli_installed": kraken_cli.is_installed(),
            "kraken_cli_version": kraken_cli.get_version(),
            "db": storage.db_healthcheck(),
            "env": safe_env_snapshot(),
            "now": utc_now_iso(),
        }
    )


__all__ = ["app"]
