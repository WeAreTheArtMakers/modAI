"""Read-only runtime diagnostics, including two real local model probes."""
from __future__ import annotations

import importlib.metadata
import shutil
import sys
from pathlib import Path
from typing import Any

from modai.models.ollama import OllamaRuntime


def diagnose(settings: Any, client: Any = None) -> dict[str, Any]:
    checks: list[dict[str, str]] = []
    def add(name: str, verdict: str, detail: str = "") -> None:
        checks.append({"name": name, "verdict": verdict, "detail": detail})
    add("Python", "PASS" if sys.version_info >= (3, 10) else "FAIL", sys.executable)
    add("Virtual environment", "PASS" if sys.prefix != sys.base_prefix else "WARN", sys.prefix)
    try:
        add("ollama-python", "PASS", importlib.metadata.version("ollama"))
        if client is None:
            from ollama import Client
            client = Client(host=settings.host, trust_env=False, timeout=min(settings.model_timeout_seconds, 90))
        client.list()
        add("Ollama server", "PASS", settings.host)
        info = client.show(settings.model)
        add("Model available", "PASS", settings.model)
        runtime = OllamaRuntime(client, settings.model, options={"think": False, "num_ctx": 2048,
                                "num_predict": 96, "temperature": 0}, keep_alive=settings.keep_alive)
        chunks: list[str] = []
        result = runtime.generate([{"role": "user", "content": "Reply exactly: MODAI_OK"}], [], on_text=chunks.append)
        add("Streaming", "PASS" if chunks else "FAIL", f"{len(chunks)} visible chunks")
        add("Visible response", "PASS" if "MODAI_OK" in result.content else "FAIL",
            result.error_code or result.content[:120])
        add("think=false", "PASS" if not result.thinking else "FAIL",
            "explicit top-level think=False; thinking characters=" + str(len(result.thinking)))
        schema = {"type": "function", "function": {"name": "doctor_echo",
            "description": "Test-only echo; never executes commands or writes files.",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}}
        result = runtime.generate([{"role": "user", "content": 'Call doctor_echo with text="MODAI_OK". No prose.'}], [schema])
        ok = any(c.name == "doctor_echo" and c.arguments == {"text": "MODAI_OK"} for c in result.tool_calls)
        add("Native tool calling", "PASS" if ok else "FAIL", "validated only; no tool executed")
    except Exception as exc:
        add("Runtime probe", "FAIL", f"{type(exc).__name__}: {exc}")
    for name in ("ollama-python", "Ollama server", "Model available", "Streaming", "Visible response", "think=false", "Native tool calling"):
        if not any(c["name"] == name for c in checks):
            add(name, "FAIL", "not reached because a prerequisite failed")
    workspace = Path(settings.workspace).expanduser().resolve()
    add("Workspace", "PASS" if workspace.is_dir() else "FAIL", str(workspace))
    for name, executable in (("Git", "git"), ("ripgrep", "rg")):
        found = shutil.which(executable)
        add(name, "PASS" if found else "WARN", found or "not installed")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        add("Browser validator", "PASS", "Chromium launched")
    except Exception as exc:
        add("Browser validator", "WARN", str(exc)[:250])
    return {"verdict": "FAIL" if any(c["verdict"] == "FAIL" for c in checks) else "PASS",
            "model": settings.model, "context": settings.context_size, "checks": checks}


def render(report: dict[str, Any]) -> str:
    return "MODAI DOCTOR\n\n" + "\n".join(
        f"{c['name']:<22} {c['verdict']:<5} {c['detail']}" for c in report["checks"])
