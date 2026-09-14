from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

from runtime_context import get_workspace
from tools.web_assets import validate_web_assets


IGNORED_DIRS = {".git", ".venv", "node_modules", "dist", "build", ".next", ".cache"}


class _PageInspector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.has_charset = False
        self.has_viewport = False
        self.title_parts: list[str] = []
        self._in_title = False
        self.ids: list[str] = []
        self.h1_count = 0
        self.has_main = False
        self.images = 0
        self.images_without_alt = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): (value or "") for name, value in attrs}
        normalized = tag.lower()
        if normalized == "html":
            self.lang = values.get("lang", "").strip()
        elif normalized == "meta":
            self.has_charset = self.has_charset or bool(values.get("charset", "").strip())
            self.has_viewport = self.has_viewport or values.get("name", "").lower() == "viewport"
        elif normalized == "title":
            self._in_title = True
        elif normalized == "h1":
            self.h1_count += 1
        elif normalized == "main":
            self.has_main = True
        elif normalized == "img":
            self.images += 1
            if "alt" not in values:
                self.images_without_alt += 1
        if values.get("id"):
            self.ids.append(values["id"])

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)


def _inside(root: Path, workspace: Path) -> bool:
    return root == workspace or workspace in root.parents


def _source_files(root: Path, suffix: str) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix.lower() == suffix else []
    return [
        item for item in root.rglob(f"*{suffix}")
        if item.is_file() and not any(part in IGNORED_DIRS for part in item.parts)
    ][:200]


def _balanced_css(path: Path) -> bool:
    text = path.read_text(encoding="utf-8", errors="replace")[:2_000_000]
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"(['\"])(?:\\.|(?!\1).)*\1", "", text)
    depth = 0
    for character in text:
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def validate_static_site(path: str = ".") -> str:
    """Run deterministic offline checks for a static HTML/CSS/JS application."""
    workspace = get_workspace()
    root = (workspace / path).resolve()
    if not _inside(root, workspace):
        raise ValueError("Path escapes workspace")
    if not root.exists():
        raise FileNotFoundError(path)

    html_files = _source_files(root, ".html")
    if not html_files:
        return json.dumps({
            "verdict": "SKIP", "reason": "No HTML files found", "errors": [], "warnings": [],
        }, ensure_ascii=False, indent=2)

    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, object] = {}
    asset_report = json.loads(validate_web_assets(path))
    checks["assets"] = asset_report
    if asset_report.get("verdict") == "FAIL":
        errors.append(f"{asset_report.get('missing_count', 0)} referenced local asset(s) are missing")

    for html_file in html_files:
        relative = str(html_file.relative_to(workspace))
        parser = _PageInspector()
        try:
            parser.feed(html_file.read_text(encoding="utf-8", errors="replace")[:2_000_000])
            parser.close()
        except Exception as exc:
            errors.append(f"{relative}: HTML parse error: {exc}")
            continue
        duplicates = sorted({identifier for identifier in parser.ids if parser.ids.count(identifier) > 1})
        if duplicates:
            errors.append(f"{relative}: duplicate id(s): {', '.join(duplicates[:20])}")
        if not parser.lang:
            warnings.append(f"{relative}: html lang attribute is missing")
        if not parser.has_charset:
            warnings.append(f"{relative}: meta charset is missing")
        if not parser.has_viewport:
            errors.append(f"{relative}: responsive viewport meta tag is missing")
        if not "".join(parser.title_parts).strip():
            errors.append(f"{relative}: non-empty title is required")
        if parser.h1_count != 1:
            warnings.append(f"{relative}: expected one h1, found {parser.h1_count}")
        if not parser.has_main:
            warnings.append(f"{relative}: main landmark is missing")
        if parser.images_without_alt:
            errors.append(f"{relative}: {parser.images_without_alt}/{parser.images} image(s) have no alt attribute")

    css_files = _source_files(root, ".css")
    unbalanced_css = [str(item.relative_to(workspace)) for item in css_files if not _balanced_css(item)]
    if unbalanced_css:
        errors.append("Unbalanced CSS braces: " + ", ".join(unbalanced_css[:20]))
    checks["css_files"] = len(css_files)

    js_files = _source_files(root, ".js")
    node = shutil.which("node")
    js_failures: list[str] = []
    if node:
        for js_file in js_files[:100]:
            result = subprocess.run(
                [node, "--check", str(js_file)], cwd=workspace,
                capture_output=True, text=True, timeout=20, check=False,
            )
            if result.returncode:
                detail = (result.stderr or result.stdout).strip().splitlines()
                js_failures.append(f"{js_file.relative_to(workspace)}: {detail[-1] if detail else 'syntax error'}")
        errors.extend(js_failures)
    elif js_files:
        warnings.append("Node.js is unavailable; JavaScript syntax check was skipped")
    checks["javascript_files"] = len(js_files)
    checks["javascript_checked"] = bool(node)

    return json.dumps({
        "verdict": "FAIL" if errors else "PASS",
        "html_files": len(html_files),
        "checks": checks,
        "errors": errors[:100],
        "warnings": warnings[:100],
    }, ensure_ascii=False, indent=2)
