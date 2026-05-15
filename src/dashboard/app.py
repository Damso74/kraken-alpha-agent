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
