from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class IsolatedWorktree:
    repository: Path
    path: Path

    @classmethod
    def create(cls, repository: Path, label: str) -> "IsolatedWorktree":
        repository = repository.resolve()
        if not (repository / ".git").exists():
            raise ValueError("Writer isolation requires a Git repository")
        status = _git(repository, ["status", "--porcelain"])
        if status.strip():
            raise ValueError("Parallel writers require a clean checkout; use the serialized writer queue")
        path = Path(tempfile.mkdtemp(prefix=f"modai-{_safe_label(label)}-"))
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(path), "HEAD"], cwd=repository,
            capture_output=True, text=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            path.rmdir()
            raise RuntimeError(result.stderr.strip() or "Unable to create Git worktree")
        return cls(repository, path)

    def patch(self) -> bytes:
        subprocess.run(
            ["git", "add", "-N", "."], cwd=self.path,
            capture_output=True, timeout=30, check=False,
        )
        result = subprocess.run(
            ["git", "diff", "--binary", "--no-ext-diff"], cwd=self.path,
            capture_output=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.decode("utf-8", "replace").strip())
        return result.stdout

    def merge(self, patch: bytes) -> None:
        self.merge_into(self.repository, patch)

    @staticmethod
    def merge_into(repository: Path, patch: bytes) -> None:
        if not patch:
            return
        result = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"], cwd=repository,
            input=patch, capture_output=True, timeout=30, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Lead Arranger merge conflict: " + result.stderr.decode("utf-8", "replace").strip())

    def close(self) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(self.path)], cwd=self.repository,
            capture_output=True, timeout=30, check=False,
        )

    def __enter__(self) -> "IsolatedWorktree":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _git(repository: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repository, capture_output=True, text=True, timeout=15, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Git command failed")
    return result.stdout


def _safe_label(label: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in label)[:32] or "writer"
