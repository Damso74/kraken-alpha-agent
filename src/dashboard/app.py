"""Minimal trading-terminal style dashboard for the Kraken Alpha Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import kraken_cli, storage
from ..config import get_settings, safe_env_snapshot
from ..logger import get_logger
from ..pnl import compute_pnl
from ..portfolio import get_snapshot
from ..utils import fmt_money, utc_now_iso

logger = get_logger(__name__)

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


def _common_context() -> dict[str, Any]:
    settings = get_settings()
    portfolio_snap = get_snapshot()
    pnl = compute_pnl(portfolio_snap)
    decisions = storage.fetch_recent_decisions(limit=10)
    orders = storage.fetch_recent_orders(limit=10)
    errors = storage.fetch_recent_errors(limit=5)
    last_decision = decisions[0] if decisions else None
    last_order = orders[0] if orders else None
    return {
        "settings": settings,
        "env_snapshot": safe_env_snapshot(),
        "portfolio": portfolio_snap,
        "pnl": pnl,
        "decisions": decisions,
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
