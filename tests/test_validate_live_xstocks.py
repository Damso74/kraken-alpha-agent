"""``scripts/validate_live_xstocks.py`` safety tests.

We never invoke the real Kraken CLI. The tests cover:

- Every command built by ``build_validate_command`` carries ``--validate``,
  ``--asset-class tokenized_asset`` and ``--type market``.
- The builder rejects unsafe inputs (missing slash form, negative volume,
  bogus side).
- When ``KRAKEN_API_KEY`` is missing the script exits with code 2 without
  invoking subprocess.
- A round-trip with a mocked ``subprocess.run`` writes the expected JSON
  files (timestamped + latest) and the symbol's ``ok`` flag is set.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def validate_module():
    root = Path(__file__).resolve().parent.parent
    script = root / "scripts" / "validate_live_xstocks.py"
    spec = importlib.util.spec_from_file_location("validate_live_xstocks", script)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_builder_always_includes_validate(validate_module) -> None:
    cmd = validate_module.build_validate_command(
        symbol_pair="AAPLx/USD", volume=0.001, side="buy", order_type="market"
    )
    assert "--validate" in cmd
    assert "--asset-class" in cmd
    assert "tokenized_asset" in cmd
    assert "market" in cmd
    # Side / pair are positional after the subcommand name.
    assert cmd[0] == "order"
    assert cmd[1] == "buy"
    assert cmd[2] == "AAPLx/USD"


def test_builder_rejects_missing_slash_form(validate_module) -> None:
    with pytest.raises(ValueError):
        validate_module.build_validate_command(
            symbol_pair="AAPLxUSD", volume=0.001
        )


def test_builder_rejects_bad_volume(validate_module) -> None:
    with pytest.raises(ValueError):
        validate_module.build_validate_command(
            symbol_pair="AAPLx/USD", volume=0.0
        )


def test_builder_rejects_bad_side(validate_module) -> None:
    with pytest.raises(ValueError):
        validate_module.build_validate_command(
            symbol_pair="AAPLx/USD", volume=0.001, side="hold"
        )


def test_missing_api_key_exits_with_2(validate_module, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KRAKEN_API_KEY", "")
    monkeypatch.setenv("KRAKEN_API_SECRET", "")
    rc = validate_module.main(
        ["--symbols", "AAPLx/USD", "--volume", "0.001", "--output-dir", str(tmp_path)]
    )
    assert rc == 2
    latest = tmp_path / "validate_live_xstocks_latest.json"
    payload = json.loads(latest.read_text(encoding="utf-8"))
    assert payload["source"] == "validate_only"
    assert payload["ok"] is False
    # No commands sent — the run never reaches subprocess.
    assert payload["results"] == []


def test_happy_path_writes_outputs(validate_module, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("KRAKEN_API_KEY", "dummy-key-AAAAA")
    monkeypatch.setenv("KRAKEN_API_SECRET", "dummy-secret-BBBBB")

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = json.dumps({"validate": "ok", "ordertxids": []})
            self.stderr = ""
            self.returncode = 0

    seen_cmds: list[list[str]] = []

    def _fake_run(cmd, **kwargs):
        seen_cmds.append(list(cmd))
        return _FakeProc()

    monkeypatch.setattr(validate_module.subprocess, "run", _fake_run)

    rc = validate_module.main(
        ["--symbols", "AAPLx/USD", "NVDAx/USD", "--volume", "0.001",
         "--output-dir", str(tmp_path)]
    )
    assert rc == 0
    assert (tmp_path / "validate_live_xstocks_latest.json").exists()
    timestamped = list(tmp_path.glob("validate_live_xstocks_*.json"))
    assert len(timestamped) == 2  # one timestamped + the latest copy
    payload = json.loads(
        (tmp_path / "validate_live_xstocks_latest.json").read_text(encoding="utf-8")
    )
    assert payload["ok"] is True
    assert all(r["ok"] for r in payload["results"])

    # Every actual subprocess call carries --validate.
    assert seen_cmds, "no subprocess calls captured"
    for cmd in seen_cmds:
        joined = " ".join(cmd)
        assert "--validate" in joined
        assert "tokenized_asset" in joined


def test_secret_masking_in_stderr_output(validate_module, monkeypatch, tmp_path) -> None:
    secret = "very-secret-AAAAAAAA"
    monkeypatch.setenv("KRAKEN_API_KEY", "dummy-AAAAA")
    monkeypatch.setenv("KRAKEN_API_SECRET", secret)

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = ""
            self.stderr = f"error contains {secret} oops"
            self.returncode = 1

    monkeypatch.setattr(
        validate_module.subprocess, "run", lambda *a, **kw: _FakeProc()
    )
    rc = validate_module.main(
        ["--symbols", "AAPLx/USD", "--volume", "0.001", "--output-dir", str(tmp_path)]
    )
    assert rc == 1
    body = (tmp_path / "validate_live_xstocks_latest.json").read_text(encoding="utf-8")
    assert secret not in body
    assert "***" in body
