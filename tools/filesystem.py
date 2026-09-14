from __future__ import annotations

import os
from pathlib import Path

from runtime_context import get_workspace


IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__", ".next", ".cache"}


def _safe(path: str) -> Path:
    workspace = get_workspace()
    target = (workspace / path).resolve()
    if target != workspace and workspace not in target.parents:
        raise ValueError("Path escapes workspace")
    return target


def list_files(path: str = ".", max_files: int = 500) -> str:
    workspace = get_workspace()
    base = _safe(path)
    if not base.exists():
        return "Path does not exist."
    if base.is_file():
        return str(base.relative_to(workspace))
    files: list[str] = []
    for root, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = sorted(item for item in dirs if item not in IGNORED_DIRS and not item.startswith(".git"))
        for name in sorted(names):
            candidate = Path(root) / name
            try:
                relative = candidate.relative_to(workspace)
            except ValueError:
                continue
            files.append(str(relative))
            if len(files) >= max(1, min(int(max_files), 2000)):
                return "\n".join(files) + "\n…(liste sınırlandı)"
    return "\n".join(files) or "(no files)"


def read_file(path: str, start_line: int = 1, end_line: int = 0, max_chars: int = 30000) -> str:
    target = _safe(path)
    if not target.is_file():
        raise FileNotFoundError(path)
    max_chars = max(100, min(int(max_chars), 60000))
    lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
    start = max(1, int(start_line))
    end = len(lines) if int(end_line) <= 0 else min(len(lines), int(end_line))
    selected = lines[start - 1:end]
    body = "\n".join(f"{number:>5} | {line}" for number, line in enumerate(selected, start))
    return body[:max_chars]


def write_file(path: str, content: str) -> str:
    workspace = get_workspace()
    target = _safe(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {target.relative_to(workspace)} ({len(content.encode('utf-8'))} bytes)"


def make_directory(path: str) -> str:
    workspace = get_workspace()
    target = _safe(path)
    target.mkdir(parents=True, exist_ok=True)
    return f"Created directory {target.relative_to(workspace)}"


def replace_in_file(path: str, old: str, new: str, count: int = 1) -> str:
    workspace = get_workspace()
    target = _safe(path)
    if not target.is_file():
        raise FileNotFoundError(path)
    if not old:
        raise ValueError("old metni boş olamaz")
    original = target.read_text(encoding="utf-8")
    occurrences = original.count(old)
    if occurrences == 0:
        raise ValueError("Değiştirilecek metin dosyada bulunamadı")
    limit = max(1, min(int(count), occurrences))
    target.write_text(original.replace(old, new, limit), encoding="utf-8")
    return f"Updated {target.relative_to(workspace)} ({limit} replacement)"


def search_files(query: str, path: str = ".", max_results: int = 100) -> str:
    if not query:
        raise ValueError("Arama metni boş olamaz")
    workspace = get_workspace()
    base = _safe(path)
    results: list[str] = []
    if base.is_file():
        candidates = [base]
    else:
        candidates: list[Path] = []
        for root, dirs, names in os.walk(base, followlinks=False):
            dirs[:] = [item for item in dirs if item not in IGNORED_DIRS]
            candidates.extend(Path(root) / name for name in names)
    for candidate in candidates:
        try:
            if candidate.stat().st_size > 2_000_000:
                continue
            lines = candidate.read_text(encoding="utf-8", errors="replace").splitlines()
        except (OSError, UnicodeError):
            continue
        for number, line in enumerate(lines, 1):
            if query.lower() in line.lower():
                results.append(f"{candidate.relative_to(workspace)}:{number}: {line[:300]}")
                if len(results) >= max(1, min(int(max_results), 500)):
                    return "\n".join(results) + "\n…(sonuçlar sınırlandı)"
    return "\n".join(results) or "(no matches)"
def file_exists(path: str) -> bool:
    return _safe(path).exists()
