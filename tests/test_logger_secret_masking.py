"""Unit tests for ``src.logger`` secret masking helpers."""

from __future__ import annotations

import logging
import os

import pytest

from src.logger import _mask_scalar, mask_secrets, sanitize_payload, setup_logging


@pytest.fixture(autouse=True)
def _clear_sensitive_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(("KRAKEN_", "FEATHERLESS_", "VULTR_")) or name.endswith(
            ("_KEY", "_SECRET", "_TOKEN")
        ):
            monkeypatch.delenv(name, raising=False)


def test_mask_scalar_empty_and_short():
    assert _mask_scalar("") == ""
    assert _mask_scalar("abc") == "***"
    assert _mask_scalar("123456") == "***"


def test_mask_scalar_long_shows_prefix_suffix():
    assert _mask_scalar("abcdefghijklmnop") == "abc...nop"


def test_mask_secrets_replaces_known_env_values(monkeypatch):
    secret = "super-secret-kraken-value-12345"
    monkeypatch.setenv("KRAKEN_API_SECRET", secret)
    text = f"failed auth with secret={secret} trailing"
    masked = mask_secrets(text)
    assert secret not in masked
    assert "sup...345" in masked


def test_mask_secrets_kraken_featherless_vultr_env_prefixes(monkeypatch):
    monkeypatch.setenv("VULTR_API_KEY", "vultr-key-ABCDEFGHIJ")
    monkeypatch.setenv("FEATHERLESS_API_KEY", "featherless-KEY-123456789")
    text = "keys vultr-key-ABCDEFGHIJ and featherless-KEY-123456789"
    masked = mask_secrets(text)
    assert "vultr-key-ABCDEFGHIJ" not in masked
    assert "featherless-KEY-123456789" not in masked


def test_mask_secrets_token_suffix_env(monkeypatch):
    fake_github_token = "ghp_FAKE_TEST_TOKEN_NOT_REAL_abc123xyz"
    monkeypatch.setenv("GITHUB_TOKEN", fake_github_token)
    text = f"Authorization failed {fake_github_token}"
    masked = mask_secrets(text)
    assert fake_github_token not in masked


def test_mask_secrets_authorization_and_bearer_headers():
    fake_bearer_token = "fake-test-token-not-a-real-secret-abc123xyz"
    text = f"Authorization: Bearer {fake_bearer_token}"
    masked = mask_secrets(text)
    assert fake_bearer_token not in masked
    assert "Bearer" in masked


def test_mask_secrets_api_key_assignment_patterns():
    text = "config api_key=AbCdEfGhIjKlMnOp and api-secret: Zx9+y/QwErTyUiOp"
    masked = mask_secrets(text)
    assert "AbCdEfGhIjKlMnOp" not in masked
    assert "Zx9+y/QwErTyUiOp" not in masked


def test_mask_secrets_private_key_block():
    pem = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "FAKE_TEST_ONLY_NOT_A_REAL_PRIVATE_KEY\n"
        "-----END RSA PRIVATE KEY-----"
    )
    masked = mask_secrets(pem)
    assert "FAKE_TEST_ONLY_NOT_A_REAL_PRIVATE_KEY" not in masked
    assert "***PRIVATE_KEY***" in masked


def test_mask_secrets_long_base64_like_blob():
    blob = "FAKEBASE64NOTAREALSECRET1234567890="
    masked = mask_secrets(f"wire payload {blob} end")
    assert blob not in masked


def test_sanitize_payload_recursive_dict_and_list():
    payload = {
        "api_key": "short",
        "nested": {
            "authorization": "Bearer abcdefghijklmnopqrst",
            "safe": "hello",
        },
        "items": ["keep", "KRAKEN_API_KEY=embedded-secret-value-xyz"],
        "empty": "",
    }
    out = sanitize_payload(payload)
    assert out["api_key"] == "***"
    assert out["nested"]["authorization"] == "Bea...rst"
    assert out["nested"]["safe"] == "hello"
    assert out["empty"] == ""
    assert isinstance(out["items"], list)
    assert "embedded-secret-value-xyz" not in str(out["items"][1])


def test_sanitize_payload_preserves_non_string_types():
    payload = {"count": 42, "ratio": 0.5, "enabled": True, "missing": None}
    assert sanitize_payload(payload) == payload


def test_masking_formatter_scrubs_log_records(monkeypatch):
    monkeypatch.setenv("KRAKEN_API_KEY", "live-key-ABCDEFGHIJKLMN")
    setup_logging("DEBUG")
    logger = logging.getLogger("test.logger.masking")
    records: list[str] = []

    class _CaptureHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = _CaptureHandler()
    handler.setFormatter(logging.getLogger().handlers[0].formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    secret = "live-key-ABCDEFGHIJKLMN"
    logger.info("using key %s", secret)
    assert records
    assert secret not in records[0]
