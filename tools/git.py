from __future__ import annotations

import subprocess

from runtime_context import get_workspace


def _git(*args: str) -> str:
    process = subprocess.run(
        ["git", *args], cwd=get_workspace(), capture_output=True, text=True, timeout=60
    )
    return f"exit_code={process.returncode}\n{process.stdout}{process.stderr}".strip()[:30000]


def git_status() -> str:
    return _git("status", "--short")


def git_diff() -> str:
    return _git("diff", "--", ".")
