from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from runtime_context import get_workspace


HTML_REFERENCE = re.compile(r"(?:src|href)\s*=\s*(['\"])(.*?)\1", re.I)
CSS_REFERENCE = re.compile(r"url\(\s*(['\"]?)(.*?)\1\s*\)", re.I)
IGNORED_PREFIXES = ("#", "data:", "http://", "https://", "//", "mailto:", "tel:", "javascript:")


def _local_target(source: Path, reference: str, workspace: Path) -> Path | None:
    cleaned = unquote(reference.strip())
    if not cleaned or cleaned.lower().startswith(IGNORED_PREFIXES):
        return None
    path = urlsplit(cleaned).path
    if not path:
        return None
    target = (workspace / path.lstrip("/")) if path.startswith("/") else (source.parent / path)
    resolved = target.resolve()
    if resolved != workspace and workspace not in resolved.parents:
        raise ValueError(f"Web asset reference escapes workspace: {reference}")
    return resolved


def validate_web_assets(path: str = ".") -> str:
    """Verify local files referenced by HTML and CSS without fetching remote assets."""
    workspace = get_workspace()
    root = (workspace / path).resolve()
    if root != workspace and workspace not in root.parents:
        raise ValueError("Path escapes workspace")
    if not root.exists():
        raise FileNotFoundError(path)
    sources = [root] if root.is_file() else [
        item for item in root.rglob("*")
        if item.is_file() and item.suffix.lower() in {".html", ".htm", ".css"}
        and not any(part in {".git", ".venv", "node_modules", "dist", "build"} for part in item.parts)
    ]
    checked: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []
    for source in sorted(sources)[:200]:
        text = source.read_text(encoding="utf-8", errors="replace")[:2_000_000]
        matches = HTML_REFERENCE.finditer(text) if source.suffix.lower() in {".html", ".htm"} else CSS_REFERENCE.finditer(text)
        for match in matches:
            reference = match.group(2)
            target = _local_target(source, reference, workspace)
            if target is None:
                continue
            try:
                relative_target = str(target.relative_to(workspace))
            except ValueError:
                relative_target = str(target)
            record = {
                "source": str(source.relative_to(workspace)),
                "reference": reference,
                "target": relative_target,
            }
            checked.append(record)
            if not target.is_file():
                missing.append(record)
    return json.dumps({
        "verdict": "PASS" if not missing else "FAIL",
        "source_files": len(sources),
        "local_references_checked": len(checked),
        "missing_count": len(missing),
        "missing": missing[:100],
    }, ensure_ascii=False, indent=2)
