from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from modai.core.contracts import infer_contract


@dataclass(slots=True)
class CheckResult:
    name: str
    verdict: str
    errors: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class VerificationReport:
    verdict: str
    checks: list[CheckResult]
    sequence: int
    changed_paths: list[str]

    @property
    def errors(self) -> list[str]:
        return [f"{check.name}: {error}" for check in self.checks for error in check.errors]

    def as_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "sequence": self.sequence,
                "changed_paths": self.changed_paths,
                "checks": [{"name": item.name, "verdict": item.verdict,
                            "errors": item.errors, "details": item.details} for item in self.checks]}


def is_static_site_task(task: str, workspace: Path) -> bool:
    folded = task.casefold()
    return (workspace / "index.html").exists() or any(marker in folded for marker in (
        "landing page", "landpage", "website", "web site", "web sitesi", "index.html",
        "html", "responsive", "statik site", "web sayfası",
    ))


def requires_artifact_change(task: str) -> bool:
    folded = task.casefold()
    return any(marker in folded for marker in (
        "create", "build", "implement", "fix", "repair", "edit", "write", "refactor", "migrate",
        "oluştur", "yap", "uygula", "düzelt", "onar", "yaz", "geliştir", "ekle", "kaldır",
        "code", "kod", "landing", "website", "uygulama",
    ))


def project_snapshot(workspace: Path, limit: int = 160) -> str:
    files: list[str] = []
    for item in sorted(workspace.rglob("*")):
        if any(part in {".git", ".venv", "node_modules", "__pycache__", ".modai"} for part in item.parts):
            continue
        files.append(str(item.relative_to(workspace)) + ("/" if item.is_dir() else ""))
        if len(files) >= limit:
            files.append("…")
            break
    return "\n".join(files) or "(empty directory)"


def project_instructions(workspace: Path) -> str:
    blocks: list[str] = []
    for name in ("AGENTS.md", "MODAI.md"):
        candidate = workspace / name
        if candidate.is_file():
            blocks.append(f"## {name}\n{candidate.read_text(encoding='utf-8', errors='replace')[:12000]}")
    return "\n\n".join(blocks)


class ProjectVerifier:
    def __init__(self, workspace: Path, task: str, command_runner: Callable[[list[str], int], dict[str, Any]],
                 write_allowed: bool = True) -> None:
        self.workspace = workspace
        self.task = task
        self.command_runner = command_runner
        self.write_allowed = write_allowed
        self.sequence = 0

    def _command_checks(self) -> list[CheckResult]:
        commands: list[tuple[str, list[str]]] = []
        package = self.workspace / "package.json"
        if package.is_file():
            try:
                scripts = json.loads(package.read_text(encoding="utf-8")).get("scripts", {})
            except (json.JSONDecodeError, OSError):
                scripts = {}
            for name in ("test", "lint", "build"):
                if name in scripts:
                    commands.append((f"npm {name}", ["npm", "run", name]))
        if any(self.workspace.glob("test*.py")) or (self.workspace / "tests").is_dir():
            commands.append(("pytest", ["python3", "-m", "pytest", "-q"]))
        results: list[CheckResult] = []
        for name, command in commands[:4]:
            try:
                result = self.command_runner(command, 300)
                verdict = "PASS" if result.get("exit_code") == 0 else "FAIL"
                details = {"argv": command, "exit_code": result.get("exit_code"),
                           "output": result.get("output", "")[-4000:]}
                errors = [] if verdict == "PASS" else [details["output"] or f"exit {details['exit_code']}"]
            except Exception as exc:
                verdict, details, errors = "FAIL", {"argv": command}, [str(exc)]
            results.append(CheckResult(name, verdict, errors, details))
        return results

    def verify(self, changed_paths: list[str]) -> VerificationReport:
        self.sequence += 1
        contract = infer_contract(self.task)
        missing = [path for path in contract.files if not (self.workspace / path).is_file()
                   or (self.workspace / path).stat().st_size == 0]
        checks = [CheckResult("artifact_contract", "FAIL" if missing else "PASS",
                              [f"required file is missing or empty: {path}" for path in missing],
                              contract.as_dict())] if contract.files else []
        checks.extend(self._command_checks())
        if is_static_site_task(self.task, self.workspace):
            from runtime_context import set_workspace
            from tools.browser_gate import validate_browser_quality
            from tools.static_site import validate_static_site
            set_workspace(self.workspace)
            for name, function in (("static_site", validate_static_site),
                                   ("browser_quality", validate_browser_quality)):
                try:
                    payload = json.loads(function("."))
                    verdict = str(payload.get("verdict", "FAIL"))
                    errors = [str(item) for item in payload.get("errors", [])]
                    if verdict == "SKIP":
                        verdict, errors = "FAIL", ["required static-site evidence was skipped"]
                except Exception as exc:
                    verdict, payload, errors = "FAIL", {}, [f"{type(exc).__name__}: {exc}"]
                checks.append(CheckResult(name, verdict, errors, payload))
        verdict = "PASS" if checks and all(item.verdict == "PASS" for item in checks) else "FAIL"
        if not checks:
            if not self.write_allowed or not requires_artifact_change(self.task):
                checks.append(CheckResult("read_only_analysis", "PASS"))
            else:
                checks.append(CheckResult("artifact_change", "PASS" if changed_paths else "FAIL",
                                          [] if changed_paths else ["no artifact was changed"]))
            verdict = checks[0].verdict
        return VerificationReport(verdict, checks, self.sequence, sorted(changed_paths))
