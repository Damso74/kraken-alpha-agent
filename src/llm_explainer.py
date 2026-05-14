"""Optional Featherless-powered explainer.

Constraints:
- The LLM never overrides the deterministic engine. It only produces a JSON
  explanation that gets attached to the decision record.
- If ``FEATHERLESS_API_KEY`` is not set, the explainer returns ``None`` and
  the rest of the pipeline carries on.
- The model timeout is short so the agent loop stays responsive.
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from .config import get_settings
from .logger import get_logger
from .schemas import Decision, LLMExplanation

logger = get_logger(__name__)


_SYSTEM_PROMPT = (
    "You are an explanation assistant for an autonomous xStocks trading agent. "
    "You receive a deterministic trading decision and return a strict JSON "
    "object describing it. You never change the action, score, or size. "
    "Be concise, factual, and avoid financial advice."
)


def _user_prompt(decision: Decision) -> str:
    payload = {
        "symbol": decision.symbol,
        "action": decision.action,
        "final_score": round(decision.final_score, 3),
        "confidence": round(decision.confidence, 3),
        "regime": decision.regime,
        "votes": [v.model_dump() for v in decision.votes],
        "features": decision.features.model_dump(),
        "risk_reasons": decision.risk.reasons,
        "approved_size_usd": decision.approved_size_usd,
    }
    return (
        "Decision payload:\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
        + '\n\nReturn JSON with this exact shape: {"summary": str, '
        '"why_this_trade": str, "risk_notes": str, "confidence_comment": str}'
    )


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        # Remove ``` and optional ```json fences.
        parts = text.split("```")
        if len(parts) >= 2:
            inner = parts[1]
            if inner.lower().startswith("json"):
                inner = inner[4:]
            return inner.strip()
    return text


def explain(decision: Decision) -> LLMExplanation | None:
    settings = get_settings()
    api_key = settings.env.featherless_api_key
    if not api_key:
        return None
    model = settings.env.featherless_model or settings.config.llm.model
    if not model:
        logger.warning("Featherless API key present but no FEATHERLESS_MODEL set, skipping explainer")
        return None
    base = settings.env.featherless_base_url.rstrip("/")
    url = f"{base}/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": _user_prompt(decision)},
        ],
        "temperature": 0.2,
        "max_tokens": 400,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    timeout = settings.config.llm.timeout_seconds
    try:
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Featherless explainer failed: %s", exc)
        return None
    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        logger.warning("Featherless explainer returned unexpected payload")
        return None
    try:
        parsed = json.loads(_strip_fence(content))
    except json.JSONDecodeError:
        logger.warning("Featherless explainer did not return valid JSON")
        return None
    if not isinstance(parsed, dict):
        return None
    return LLMExplanation(
        summary=str(parsed.get("summary", ""))[:1000],
        why_this_trade=str(parsed.get("why_this_trade", ""))[:1000],
        risk_notes=str(parsed.get("risk_notes", ""))[:1000],
        confidence_comment=str(parsed.get("confidence_comment", ""))[:1000],
    )


__all__ = ["explain"]
