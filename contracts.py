from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any
from task_context import split_task


FILE_PATTERN = re.compile(
    r"(?<![\w./-])((?:[\w.-]+/)*[\w.-]+\.(?:html?|css|m?js|cjs|jsx|tsx|py|json|md|svg|png|jpe?g|webp|ico|toml|ya?ml))(?![\w-]|\.\w)",
    re.IGNORECASE,
)


def infer_artifact_contract(task: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic completion contract from the prompt and planner output."""
    instruction, _reference = split_task(task)
    task_without_urls = re.sub(r"https?://\S+", "", instruction)
    expected = {match.group(1).lstrip("./") for match in FILE_PATTERN.finditer(task_without_urls)}
    planner_contract = plan.get("artifact_contract")
    expected = {path for path in expected if path.casefold() not in {'node.js', 'vue.js', 'next.js', 'react.js'}}
    if isinstance(planner_contract, dict):
        for item in planner_contract.get("files", []):
            path = item.get("path") if isinstance(item, dict) else item
            if isinstance(path, str) and path in expected and FILE_PATTERN.fullmatch(path):
                expected.add(path.strip().lstrip("./"))

    folded = instruction.casefold()
    static_site = any(marker in folded for marker in (
        "landing page", "static site", "statik site", "web page", "website",
        "index.html", "responsive", "frontend", "landpage", "landing", "web sitesi", "web sayfa",
    ))
    if static_site and not any(path.endswith((".html", ".htm")) for path in expected):
        expected.add("index.html")

    checks: list[str] = []
    if static_site:
        checks.extend(["validate_static_site", "validate_browser_quality"])
    research_required = any(bool(item.get("needs_web")) for item in plan.get("tasks", []) if isinstance(item, dict))
    return {
        "version": 1,
        "files": [{"path": path, "required": True} for path in sorted(expected)],
        "checks": checks,
        "commands": _normalize_commands(planner_contract),
        "research": {
            "required": research_required,
            "minimum_sources": 2 if research_required else 0,
            "primary_source_required": research_required,
            "url_per_external_claim": research_required,
            "dates_required": research_required,
            "confidence_required": research_required,
        },
    }


def _normalize_commands(contract: Any) -> list[dict[str, Any]]:
    if not isinstance(contract, dict):
        return []
    commands: list[dict[str, Any]] = []
    for item in contract.get("commands", [])[:12]:
        command = item.get("command") if isinstance(item, dict) else item
        if not isinstance(command, list) or not command or not all(isinstance(arg, str) for arg in command):
            continue
        commands.append({"command": command, "required": True})
    return commands


def evaluate_artifact_contract(
    contract: dict[str, Any], workspace: Path, tool_trace: list[dict[str, Any]],
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for item in contract.get("files", []):
        relative = str(item.get("path", ""))
        target = (workspace / relative).resolve()
        safe = target == workspace.resolve() or workspace.resolve() in target.parents
        exists = safe and target.is_file()
        nonempty = exists and target.stat().st_size > 0
        files.append({"path": relative, "status": "PASS" if nonempty else "FAIL"})

    checks: list[dict[str, Any]] = []
    for tool_name in contract.get("checks", []):
        latest = next((item for item in reversed(tool_trace) if item.get("tool") == tool_name), None)
        verdict = "MISSING"
        if latest is not None:
            try:
                verdict = "PASS" if latest.get("ok") and json.loads(latest.get("result", "{}" )).get("verdict") == "PASS" else "FAIL"
            except (ValueError, TypeError):
                verdict = "FAIL"
        checks.append({"tool": tool_name, "status": verdict})

    commands: list[dict[str, Any]] = []
    for item in contract.get("commands", []):
        expected = item.get("command", [])
        latest = next((trace for trace in reversed(tool_trace)
                       if trace.get("tool") == "run_terminal" and trace.get("args", {}).get("command") == expected), None)
        passed = latest and latest.get("ok") and str(latest.get("result", "")).startswith("exit_code=0\n")
        commands.append({"command": expected, "status": "PASS" if passed else "MISSING"})

    failed = any(item["status"] != "PASS" for item in files + checks + commands)
    return {
        "verdict": "FAIL" if failed else "PASS",
        "files": files,
        "checks": checks,
        "commands": commands,
    }
