"""Repository CI attestation bound to the exact tracked verification scope."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

CI_SCOPE_PATHS = (
    ".github/workflows/ci.yml",
    "requirements.txt",
    "src",
    "tests",
    "scripts",
)
SAFETY_ENV = {
    "ALLOW_LIVE_ORDERS": "false",
    "KRAKEN_CLI_TRANSPORT": "mock",
    "LIVE_TRADING": "false",
    "TRADING_MODE": "dry_run",
}


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def tracked_ci_scope_hashes(repo_root: Path) -> dict[str, str]:
    root = Path(repo_root).resolve()
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--", *CI_SCOPE_PATHS],
        cwd=root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise RuntimeError("could not enumerate tracked CI scope")
    relative_paths = sorted(item.decode("utf-8") for item in completed.stdout.split(b"\0") if item)
    if not relative_paths:
        raise RuntimeError("tracked CI scope is empty")
    hashes: dict[str, str] = {}
    for relative in relative_paths:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise RuntimeError("tracked CI path escaped repository") from exc
        if not path.is_file():
            raise RuntimeError(f"tracked CI file is missing: {relative}")
        hashes[relative.replace("\\", "/")] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def ci_scope_sha256(repo_root: Path) -> tuple[str, int]:
    hashes = tracked_ci_scope_hashes(repo_root)
    return canonical_sha256(hashes), len(hashes)


def _git_bash() -> str:
    candidates = (
        Path(r"C:\Program Files\Git\bin\bash.exe"),
        Path(r"C:\Program Files\Git\usr\bin\bash.exe"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    executable = shutil.which("bash")
    if executable:
        return executable
    raise RuntimeError("bash is required for the repository CI scope")


def _shellcheck_command(repo_root: Path, shell_files: Sequence[str]) -> list[str]:
    executable = shutil.which("shellcheck")
    if executable:
        return [executable, "-S", "error", *shell_files]
    docker = shutil.which("docker")
    if not docker:
        raise RuntimeError("shellcheck or Docker is required for the repository CI scope")
    image = "koalaman/shellcheck:stable"
    inspected = subprocess.run(
        [docker, "image", "inspect", image],
        check=False,
        capture_output=True,
        text=True,
    )
    if inspected.returncode != 0:
        raise RuntimeError("local koalaman/shellcheck:stable image is required")
    return [
        docker,
        "run",
        "--rm",
        "--network",
        "none",
        "--mount",
        f"type=bind,src={repo_root.resolve()},dst=/repo,readonly",
        "--workdir",
        "/repo",
        image,
        "-S",
        "error",
        *shell_files,
    ]


def run_repository_ci(repo_root: Path) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    initial_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if initial_status.returncode != 0 or initial_status.stdout.strip():
        raise RuntimeError("CI attestation requires a clean worktree")
    before_scope, tracked_files = ci_scope_sha256(root)
    shell_files = sorted(
        path.relative_to(root).as_posix() for path in (root / "scripts").glob("*.sh")
    )
    if not shell_files:
        raise RuntimeError("repository CI shell scope is empty")
    environment = os.environ.copy()
    environment.update(SAFETY_ENV)
    commands: list[tuple[str, list[str]]] = [
        ("ruff", [sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"]),
        ("bash_syntax", [_git_bash(), "-n", *shell_files]),
        ("shellcheck", _shellcheck_command(root, shell_files)),
        ("pytest_collect", [sys.executable, "-m", "pytest", "--collect-only", "-q"]),
        ("pytest", [sys.executable, "-m", "pytest", "-q"]),
        ("git_diff", ["git", "diff", "--exit-code"]),
    ]
    outputs: dict[str, str] = {}
    for label, command in commands:
        completed = subprocess.run(
            command,
            cwd=root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        outputs[label] = completed.stdout + completed.stderr
        if completed.returncode != 0:
            raise RuntimeError(
                f"CI attestation {label} failed ({completed.returncode}): {outputs[label][-2000:]}"
            )
    collected = sum(
        int(match.group(1))
        for match in re.finditer(r":\s+(\d+)\s*$", outputs["pytest_collect"], re.MULTILINE)
    )
    if collected <= 0:
        raise RuntimeError("could not establish pytest collected count")
    after_scope, after_count = ci_scope_sha256(root)
    if after_scope != before_scope or after_count != tracked_files:
        raise RuntimeError("tracked CI scope changed during attestation")
    final_status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if final_status.returncode != 0 or final_status.stdout.strip():
        raise RuntimeError("worktree changed during CI attestation")
    return {
        "ci_scope_sha256": before_scope,
        "ci_scope_tracked_files": tracked_files,
        "ruff_scope": "src tests scripts",
        "ruff_passed": True,
        "bash_syntax_scope": "scripts/*.sh",
        "bash_syntax_passed": True,
        "shellcheck_scope": "shellcheck -S error scripts/*.sh",
        "shellcheck_passed": True,
        "pytest_collected": collected,
        "pytest_passed": True,
        "git_diff_clean": True,
        "git_status_clean": True,
        "safety_env": SAFETY_ENV,
    }


def validate_ci_evidence(payload: dict[str, Any], repo_root: Path) -> list[str]:
    reasons: list[str] = []
    try:
        expected_scope, expected_count = ci_scope_sha256(repo_root)
    except RuntimeError:
        return ["CI_SCOPE_UNVERIFIABLE"]
    if payload.get("ci_scope_sha256") != expected_scope:
        reasons.append("CI_SCOPE_HASH_MISMATCH")
    if int(payload.get("ci_scope_tracked_files", 0)) != expected_count:
        reasons.append("CI_SCOPE_FILE_COUNT_MISMATCH")
    if payload.get("ruff_scope") != "src tests scripts" or payload.get("ruff_passed") is not True:
        reasons.append("CI_RUFF_SCOPE_NOT_VERIFIED")
    if (
        payload.get("bash_syntax_scope") != "scripts/*.sh"
        or payload.get("bash_syntax_passed") is not True
    ):
        reasons.append("CI_BASH_SYNTAX_NOT_VERIFIED")
    if (
        payload.get("shellcheck_scope") != "shellcheck -S error scripts/*.sh"
        or payload.get("shellcheck_passed") is not True
    ):
        reasons.append("CI_SHELLCHECK_NOT_VERIFIED")
    if payload.get("pytest_passed") is not True or int(payload.get("pytest_collected", 0)) <= 0:
        reasons.append("CI_PYTEST_NOT_VERIFIED")
    if payload.get("git_diff_clean") is not True:
        reasons.append("CI_GIT_DIFF_NOT_VERIFIED")
    if payload.get("git_status_clean") is not True:
        reasons.append("CI_GIT_STATUS_NOT_VERIFIED")
    if payload.get("safety_env") != SAFETY_ENV:
        reasons.append("CI_SAFETY_ENV_MISMATCH")
    return reasons
