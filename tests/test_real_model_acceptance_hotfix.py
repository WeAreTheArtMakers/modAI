"""Deterministic regressions for malformed native calls and truthful outcomes."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from config import Settings
from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall
from modai.models.fake import ScriptedRuntime
from modai.models.ollama import OllamaRuntime
from modai.tools.coding import CodingTools
from modai.tools.policy import Capabilities, ToolPolicy
from modai.tools.registry import ToolRegistry
from orchestrator import main


def _registry(root: Path) -> ToolRegistry:
    return ToolRegistry(CodingTools(root, ToolPolicy(Capabilities(write=True)), root / ".logs"))


@pytest.mark.parametrize("args,missing", [
    ({"content": "<h1>Hi</h1>"}, ["path"]),
    ({"path": "index.html"}, ["content"]),
])
def test_native_write_missing_required_returns_bounded_diagnostic(tmp_path: Path, args, missing):
    registry = _registry(tmp_path)
    result = registry.execute("write", args, allowed_schemas=registry.schemas())
    assert result["error_code"] == "INVALID_TOOL_ARGUMENTS"
    assert result["tool"] == "write"
    assert result["missing_required"] == missing
    assert result["retryable"] is True
    assert result["example"] == {"path": "index.html", "content": "..."}
    assert not (tmp_path / "index.html").exists()
    assert len(json.dumps(result)) < 500


def test_malformed_native_arguments_are_not_silently_empty(tmp_path: Path):
    class Client:
        def chat(self, **_kwargs):
            return {"message": {"tool_calls": [{"function": {
                "name": "write", "arguments": '{"path":'
            }}]}}
    response = OllamaRuntime(Client(), "mock", stream=False).generate([], _registry(tmp_path).schemas())
    call = response.tool_calls[0]
    assert call.argument_error == "malformed_json"
    result = _registry(tmp_path).execute(call.name, call.arguments,
                                         allowed_schemas=_registry(tmp_path).schemas(),
                                         argument_error=call.argument_error)
    assert result["error_code"] == "INVALID_TOOL_ARGUMENTS"
    assert not list(tmp_path.glob("*.html"))


@pytest.mark.parametrize("path", ["", " ", ".", "../escape.html", "/tmp/escape.html", ".env"])
def test_invalid_model_path_is_rejected_before_mutation(tmp_path: Path, path: str):
    registry = _registry(tmp_path)
    result = registry.execute("write", {"path": path, "content": "bad"},
                              allowed_schemas=registry.schemas())
    assert result["error_code"] == "INVALID_TOOL_ARGUMENTS"
    assert result["retryable"] is False
    assert not (tmp_path / ".env").exists()
    assert not (tmp_path / "index.html").exists()


def test_valid_write_and_legacy_alias_still_work(tmp_path: Path):
    registry = _registry(tmp_path)
    assert registry.execute("write", {"path": "index.html", "content": "good"},
                            allowed_schemas=registry.schemas())["changed"]
    assert registry.execute("write_file", {"path": "legacy.txt", "content": "kept"},
                            allowed_schemas=registry.schemas())["changed"]
    assert (tmp_path / "index.html").read_text() == "good"
    assert (tmp_path / "legacy.txt").read_text() == "kept"


def test_unadvertised_legacy_mutation_and_empty_edit_target_are_rejected(tmp_path: Path):
    registry = _registry(tmp_path)
    schemas = registry.schemas()
    result = registry.execute("make_directory", {"path": "assets"}, allowed_schemas=schemas)
    assert result["error_code"] == "INVALID_TOOL_ARGUMENTS"
    assert result["invalid_fields"] == ["tool"]
    assert not (tmp_path / "assets").exists()
    result = registry.execute("edit", {"path": "index.html", "edits": [{"old": "", "new": "x"}]},
                              allowed_schemas=schemas)
    assert result["invalid_fields"] == ["edits[0].old"]


def _harness(root: Path, responses: list[ModelResponse], task: str, **kwargs):
    runtime = ScriptedRuntime(responses)
    agent = CodingHarness(runtime=runtime, workspace=root, run_dir=root / ".run",
                          task=task, max_auto_skills=0, retry_backoff_seconds=0, **kwargs)
    return agent, runtime


def test_repeated_identical_invalid_writes_stop_at_configured_limit(tmp_path: Path):
    bad = ModelResponse(tool_calls=[ToolCall("w", "write", {"content": "fake"})])
    agent, runtime = _harness(tmp_path, [bad, bad, ModelResponse(content="I created index.html")],
                              "Create index.html", invalid_tool_limit=2)
    result = agent.run()
    assert result.status == "needs_attention"
    assert len(runtime.requests) == 2
    assert "INVALID_TOOL_ARGUMENTS" in json.dumps(agent.session.records())
    assert not (tmp_path / "index.html").exists()
    assert (tmp_path / ".run" / "session.jsonl").is_file()


def test_false_verified_claim_is_diagnostic_only_when_index_missing(tmp_path: Path):
    claim = "Verified: index.html was created and tested successfully."
    agent, _runtime = _harness(tmp_path, [ModelResponse(content=claim)],
                               "Create index.html", repair_rounds=0)
    result = agent.run()
    assert result.status == "needs_attention"
    assert result.verification["verdict"] == "FAIL"
    assert "artifact_contract" in result.final
    assert "index.html" in result.final
    assert "Requested artifact not created" in result.final
    assert "not found" in result.final or "missing" in result.final
    assert claim not in result.final
    assert claim in json.dumps(agent.session.records())


def test_failed_gates_cannot_be_replaced_by_model_prose(tmp_path: Path):
    agent, _runtime = _harness(tmp_path, [ModelResponse(content="All checks PASS.")],
                               "Create output.txt", repair_rounds=0)
    result = agent.run()
    assert result.status == "needs_attention"
    assert "artifact_change" in result.final
    assert "All checks PASS." not in result.final


def test_noninteractive_cli_uses_nonzero_status_for_harness_failure(tmp_path: Path, capsys):
    class Stub:
        def __init__(self, *_args, **_kwargs):
            self.settings = Settings(workspace=str(tmp_path))
            self._last_harness_status = "needs_attention"
        def run_task(self, *_args, **_kwargs):
            return "NEEDS_ATTENTION: index.html was not created."
    with patch("orchestrator.Orchestrator", Stub), patch("orchestrator.interactive_terminal", return_value=False):
        code = main(["--workspace", str(tmp_path), "--no-internet", "Create index.html"])
    assert code == 1
    assert "NEEDS_ATTENTION" in capsys.readouterr().out
