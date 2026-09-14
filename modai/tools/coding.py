from __future__ import annotations

import difflib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .policy import ToolPolicy


class CodingTools:
    def __init__(self, workspace: Path, policy: ToolPolicy, log_dir: Path,
                 max_output_chars: int = 12000) -> None:
        self.workspace = workspace.resolve()
        self.policy = policy
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.max_output_chars = max_output_chars
        self.mutated_paths: set[str] = set()

    def _path(self, value: str = ".", *, must_exist: bool = False) -> Path:
        candidate = (self.workspace / value).resolve()
        try:
            candidate.relative_to(self.workspace)
        except ValueError as exc:
            raise PermissionError("path escapes the working directory") from exc
        if must_exist and not candidate.exists():
            raise FileNotFoundError(value)
        return candidate

    def _relative(self, path: Path) -> str:
        return str(path.relative_to(self.workspace)) or "."

    def read(self, path: str, start_line: int = 1, end_line: int = 400) -> dict[str, Any]:
        target = self._path(path, must_exist=True)
        if not target.is_file():
            raise IsADirectoryError(path)
        if target.stat().st_size > 4_000_000:
            raise ValueError("targeted text reads are limited to 4 MB")
        lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line))
        end = min(len(lines), max(start, int(end_line)))
        numbered = "\n".join(f"{number:>5} | {lines[number - 1]}" for number in range(start, end + 1))
        return {"path": self._relative(target), "start_line": start, "end_line": end,
                "total_lines": len(lines), "content": numbered,
                "truncated": end < len(lines)}

    def ls(self, path: str = ".", depth: int = 2, limit: int = 300) -> dict[str, Any]:
        target = self._path(path, must_exist=True)
        base_parts = len(target.parts)
        entries: list[str] = []
        for item in sorted(target.rglob("*")):
            if len(item.parts) - base_parts > max(1, min(int(depth), 6)):
                continue
            if any(part in {".git", "node_modules", ".venv", "__pycache__"} for part in item.parts):
                continue
            entries.append(self._relative(item) + ("/" if item.is_dir() else ""))
            if len(entries) >= limit:
                break
        return {"path": self._relative(target), "entries": entries, "truncated": len(entries) >= limit}

    def find(self, pattern: str = "*", path: str = ".", limit: int = 200) -> dict[str, Any]:
        target = self._path(path, must_exist=True)
        matches = [self._relative(item) for item in sorted(target.rglob(pattern))
                   if ".git" not in item.parts and "node_modules" not in item.parts][:limit]
        return {"pattern": pattern, "matches": matches, "truncated": len(matches) >= limit}

    def grep(self, pattern: str, path: str = ".", glob: str | None = None,
             limit: int = 200) -> dict[str, Any]:
        target = self._path(path, must_exist=True)
        argv = ["rg", "--line-number", "--no-heading", "--color", "never", "--max-count", str(limit)]
        if glob:
            argv.extend(["--glob", glob])
        argv.extend([pattern, str(target)])
        process = subprocess.run(argv, cwd=self.workspace, text=True, capture_output=True, timeout=30)
        output = process.stdout
        if process.returncode not in {0, 1}:
            raise RuntimeError(process.stderr.strip() or "rg failed")
        return {"pattern": pattern, "matches": output[:self.max_output_chars],
                "truncated": len(output) > self.max_output_chars}

    def _atomic_write(self, target: Path, data: bytes) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def write(self, path: str, content: str) -> dict[str, Any]:
        if len(content.encode("utf-8")) > 2_000_000:
            raise ValueError("one atomic write is limited to 2 MB")
        target = self._path(path)
        before = target.read_text(encoding="utf-8", errors="replace") if target.exists() else ""
        if before == content:
            return {"path": path, "changed": False, "reason": "content is unchanged"}
        self._atomic_write(target, content.encode("utf-8"))
        self.mutated_paths.add(self._relative(target))
        return {"path": self._relative(target), "changed": True,
                "bytes": len(content.encode("utf-8")), "diff": self._diff(before, content, path)}

    def make_directory(self, path: str) -> dict[str, Any]:
        target = self._path(path)
        existed = target.exists()
        target.mkdir(parents=True, exist_ok=True)
        return {"path": self._relative(target), "changed": not existed}

    def edit(self, path: str, edits: list[dict[str, str]]) -> dict[str, Any]:
        target = self._path(path, must_exist=True)
        raw = target.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw[3:].decode("utf-8") if bom else raw.decode("utf-8")
        newline = "\r\n" if "\r\n" in text else "\n"
        normalized = text.replace("\r\n", "\n")
        ranges: list[tuple[int, int, str]] = []
        for index, edit in enumerate(edits):
            old = str(edit.get("old", "")).replace("\r\n", "\n")
            new = str(edit.get("new", "")).replace("\r\n", "\n")
            if not old:
                raise ValueError(f"edit {index}: old text must not be empty")
            count = normalized.count(old)
            if count != 1:
                raise ValueError(f"edit {index}: old text must match exactly once (found {count})")
            start = normalized.index(old)
            ranges.append((start, start + len(old), new))
        ordered = sorted(ranges)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                raise ValueError("edits overlap; no changes were applied")
        updated = normalized
        for start, end, replacement in reversed(ordered):
            updated = updated[:start] + replacement + updated[end:]
        if updated == normalized:
            return {"path": path, "changed": False, "reason": "content is unchanged"}
        serialized = updated.replace("\n", newline).encode("utf-8")
        if bom:
            serialized = b"\xef\xbb\xbf" + serialized
        self._atomic_write(target, serialized)
        self.mutated_paths.add(self._relative(target))
        return {"path": self._relative(target), "changed": True, "edits": len(edits),
                "diff": self._diff(normalized, updated, path)}

    def bash(self, argv: list[str], timeout: int = 120) -> dict[str, Any]:
        self.policy.validate_command(argv)
        log_path = self.log_dir / f"command-{len(list(self.log_dir.glob('command-*.log'))) + 1:04d}.log"
        with log_path.open("wb") as log:
            process = subprocess.run(argv, cwd=self.workspace, stdout=log, stderr=subprocess.STDOUT,
                                     timeout=max(1, min(int(timeout), 900)), check=False)
        size = log_path.stat().st_size
        with log_path.open("rb") as log:
            if size <= self.max_output_chars:
                raw = log.read()
            else:
                half = self.max_output_chars // 2
                first = log.read(half)
                log.seek(max(0, size - half))
                raw = first + b"\n... output clipped; see full_output ...\n" + log.read(half)
        output = raw.decode("utf-8", errors="replace")
        return {"argv": argv, "exit_code": process.returncode,
                "output": output, "truncated": size > self.max_output_chars,
                "full_output": str(log_path)}

    @staticmethod
    def _diff(before: str, after: str, path: str) -> str:
        value = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True),
                                             fromfile=f"a/{path}", tofile=f"b/{path}", n=3))
        return value[:8000]
