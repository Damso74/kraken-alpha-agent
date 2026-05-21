"""Structured logger with automatic secret masking.

Any value that looks like an API key/secret is masked before reaching the
formatter so it can never leak to stdout, files, or the dashboard.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from collections.abc import Iterable
from logging import LogRecord
from typing import Any

# Environment variable prefixes whose values must never appear in logs.
_SENSITIVE_ENV_PREFIXES: tuple[str, ...] = (
    "KRAKEN_",
    "FEATHERLESS_",
    "VULTR_",
)

# Environment variable suffixes (case-insensitive).
_SENSITIVE_ENV_SUFFIXES: tuple[str, ...] = (
    "_KEY",
    "_SECRET",
    "_TOKEN",
)

# Dict keys whose string values should be masked regardless of content.
_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|api[_-]?secret|authorization|bearer|token|secret|password|"
    r"private[_-]?key|kraken|featherless|vultr|access[_-]?token|refresh[_-]?token)"
)

# Patterns that match obvious credential formats even if the value is not in env.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)([A-Za-z0-9/+_\-=]{8,})"),
    re.compile(r"(?i)(api[_-]?secret\s*[=:]\s*)([A-Za-z0-9/+_\-=]{8,})"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-+/=]{8,})"),
    re.compile(
        r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)([A-Za-z0-9._\-+/=]{8,})"
    ),
    re.compile(
        r"(?i)\b("
        r"KRAKEN_[A-Z0-9_]*|FEATHERLESS_[A-Z0-9_]*|VULTR_[A-Z0-9_]*|"
        r"[A-Z0-9_]*(?:KEY|SECRET|TOKEN)"
        r")=([^\s,;\"']+)"
    ),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    ),
    # Long base64-ish blobs (20+ chars) — common for API secrets on the wire.
    re.compile(r"\b([A-Za-z0-9+/]{20,}={0,2})\b"),
)


def _is_sensitive_env_name(name: str) -> bool:
    upper = name.upper()
    if any(upper.startswith(prefix) for prefix in _SENSITIVE_ENV_PREFIXES):
        return True
    return any(upper.endswith(suffix) for suffix in _SENSITIVE_ENV_SUFFIXES)


def _mask_scalar(value: str) -> str:
    """Mask a single secret scalar: empty stays empty, short→***, long→pre...suf."""
    if not value:
        return value
    if len(value) <= 6:
        return "***"
    return f"{value[:3]}...{value[-3:]}"


def _gather_secret_values() -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for name, val in os.environ.items():
        if not val or len(val) < 6:
            continue
        if _is_sensitive_env_name(name) and val not in seen:
            seen.add(val)
            out.append(val)
    return out


def mask_secrets(text: str, extra_values: Iterable[str] | None = None) -> str:
    if not text:
        return text
    out = text
    for value in _gather_secret_values():
        if value and value in out:
            out = out.replace(value, _mask_scalar(value))
    if extra_values:
        for value in extra_values:
            if value and value in out:
                out = out.replace(value, _mask_scalar(value))
    for pat in _PATTERNS:
        if pat.groups >= 2:

            def _sub_multi(m: re.Match[str]) -> str:
                return f"{m.group(1)}{_mask_scalar(m.group(2))}"

            out = pat.sub(_sub_multi, out)
        elif pat.groups == 1:

            def _sub_single(m: re.Match[str]) -> str:
                return _mask_scalar(m.group(1))

            out = pat.sub(_sub_single, out)
        else:
            out = pat.sub("***PRIVATE_KEY***", out)
    return out


def sanitize_payload(payload: Any, extra_values: Iterable[str] | None = None) -> Any:
    """Recursively walk JSON-shaped payloads and mask secrets in strings."""
    if isinstance(payload, str):
        return mask_secrets(payload, extra_values=extra_values)
    if isinstance(payload, dict):
        sanitized: dict[Any, Any] = {}
        for key, value in payload.items():
            key_str = str(key)
            if _SENSITIVE_KEY_RE.search(key_str) and isinstance(value, str):
                sanitized[key] = _mask_scalar(value)
            else:
                sanitized[key] = sanitize_payload(value, extra_values=extra_values)
        return sanitized
    if isinstance(payload, list):
        return [sanitize_payload(item, extra_values=extra_values) for item in payload]
    if isinstance(payload, tuple):
        return tuple(sanitize_payload(item, extra_values=extra_values) for item in payload)
    return payload


class _MaskingFormatter(logging.Formatter):
    def format(self, record: LogRecord) -> str:
        original = super().format(record)
        return mask_secrets(original)


_LEVEL_DEFAULT = "INFO"


def setup_logging(level: str | None = None) -> None:
    lvl = (level or os.environ.get("LOG_LEVEL", _LEVEL_DEFAULT)).upper()
    root = logging.getLogger()
    if getattr(root, "_kaa_configured", False):
        root.setLevel(lvl)
        return
    root.setLevel(lvl)
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setLevel(lvl)
    fmt = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
    handler.setFormatter(_MaskingFormatter(fmt=fmt, datefmt="%Y-%m-%dT%H:%M:%S"))
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root._kaa_configured = True  # type: ignore[attr-defined]


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
