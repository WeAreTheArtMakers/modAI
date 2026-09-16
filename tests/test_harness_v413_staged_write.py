"""V4.1.3 bounded staged-write regression tests.

Oversized single write() calls are truncated by the model output cap before
valid tool JSON exists. The protocol bounds every model-facing write/append
chunk (MODEL_WRITE_MAX_CHARS) and bootstraps implementation with write-only:

  exploration -> boundary -> small write -> append/append/... -> verify
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.tools.coding import MODEL_WRITE_MAX_CHARS, CodingTools
from modai.tools.policy import Capabilities, ToolPolicy
from modai.tools.registry import SCHEMAS, ToolRegistry


def _call(n: int, name: str, **args) -> ToolCall:
    return ToolCall(f"c{n}", name, args)


def _harness(root: Path, responses, task: str = "Read README.md and write notes-out.md",
             **kw) -> CodingHarness:
    return CodingHarness(
        runtime=ScriptedRuntime(responses),
        workspace=root,
        run_dir=root / ".run",
        task=task,
        retry_backoff_seconds=0,
        **kw,
    )


def _tool_names(request) -> set[str]:
    return {t["function"]["name"] for t in (request.get("tools") or [])}


def _seed(root: Path) -> None:
    (root / "README.md").write_text("# MODAI\nLocal coding harness.\n")


def _make_tools(root: Path, write: bool = True) -> tuple[CodingTools, ToolRegistry]:
    tools = CodingTools(root, ToolPolicy(Capabilities(write=write)), root / ".logs")
    return tools, ToolRegistry(tools)


def _write_schema() -> dict:
    return next(s for s in SCHEMAS if s["function"]["name"] == "write")


def _append_schema() -> dict:
    return next(s for s in SCHEMAS if s["function"]["name"] == "append")


# ── 1: bootstrap schema ──────────────────────────────────────────────────────

def test_bootstrap_schema_is_write_only():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        assert agent.run().status == "completed"
        assert _tool_names(agent.runtime.requests[2]) == {"write"}


# ── 2: write schema bounded ──────────────────────────────────────────────────

def test_write_schema_is_bounded():
    content_schema = _write_schema()["function"]["parameters"]["properties"]["content"]
    assert content_schema["maxLength"] == MODEL_WRITE_MAX_CHARS == 4000


def test_append_schema_is_bounded_and_registered():
    content_schema = _append_schema()["function"]["parameters"]["properties"]["content"]
    assert content_schema["maxLength"] == MODEL_WRITE_MAX_CHARS


# ── 3: small write works ─────────────────────────────────────────────────────

def test_small_write_creates_file(tmp_path: Path):
    tools, registry = _make_tools(tmp_path)
    result = registry.execute("write", {"path": "a.txt", "content": "hello\n"})
    assert result["changed"] is True
    assert (tmp_path / "a.txt").read_text() == "hello\n"


# ── 4: oversized write rejected ──────────────────────────────────────────────

def test_oversized_write_rejected_before_mutation(tmp_path: Path):
    tools, registry = _make_tools(tmp_path)
    big = "x" * (MODEL_WRITE_MAX_CHARS + 1)
    result = registry.execute("write", {"path": "big.txt", "content": big})
    assert result.get("error_code") == "CONTENT_TOO_LARGE"
    assert result.get("retryable") is False
    assert result.get("max_chars") == MODEL_WRITE_MAX_CHARS
    assert result.get("actual_chars") == len(big)
    assert result.get("changed") is not True
    assert not (tmp_path / "big.txt").exists()
    assert "big.txt" not in tools.mutated_paths


def test_boundary_write_at_exact_limit_passes(tmp_path: Path):
    _, registry = _make_tools(tmp_path)
    result = registry.execute("write", {"path": "edge.txt", "content": "y" * MODEL_WRITE_MAX_CHARS})
    assert result["changed"] is True


def test_low_level_write_stays_unbounded_for_internal_callers(tmp_path: Path):
    tools, _ = _make_tools(tmp_path)
    result = tools.write("internal.txt", "z" * (MODEL_WRITE_MAX_CHARS + 500))
    assert result["changed"] is True


# ── 5: bootstrap remains after empty response ────────────────────────────────

def test_bootstrap_remains_after_empty_response():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(content="", tool_calls=[], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        assert agent.run().status == "completed"
        # Request after the empty turn (index 3) is still bootstrap write-only.
        assert _tool_names(agent.runtime.requests[3]) == {"write"}


# ── 6: first write unlocks normal surface incl. append ───────────────────────

def test_normal_surface_returns_with_append_after_first_write():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(
                tool_calls=[_call(4, "append", path="notes-out.md", content="more\n")],
                usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        result = agent.run()
        assert result.status == "completed"
        names = _tool_names(agent.runtime.requests[3])
        assert "append" in names and "read" in names and "bash" in names
        assert (root / "notes-out.md").read_text() == "# out\nmore\n"


# ── 7/8/9/10: append semantics ───────────────────────────────────────────────

def test_append_extends_existing_file(tmp_path: Path):
    tools, registry = _make_tools(tmp_path)
    registry.execute("write", {"path": "f.txt", "content": "one\n"})
    result = registry.execute("append", {"path": "f.txt", "content": "two\n"})
    assert result["changed"] is True
    assert (tmp_path / "f.txt").read_text() == "one\ntwo\n"


def test_append_missing_file_does_not_create(tmp_path: Path):
    _, registry = _make_tools(tmp_path)
    with pytest.raises(FileNotFoundError):
        registry.execute("append", {"path": "ghost.txt", "content": "x"})
    assert not (tmp_path / "ghost.txt").exists()


def test_append_oversized_content_rejected(tmp_path: Path):
    tools, registry = _make_tools(tmp_path)
    registry.execute("write", {"path": "f.txt", "content": "one\n"})
    result = registry.execute("append", {"path": "f.txt", "content": "x" * (MODEL_WRITE_MAX_CHARS + 1)})
    assert result.get("error_code") == "CONTENT_TOO_LARGE"
    assert (tmp_path / "f.txt").read_text() == "one\n"


def test_append_empty_content_is_noop(tmp_path: Path):
    _, registry = _make_tools(tmp_path)
    registry.execute("write", {"path": "f.txt", "content": "one\n"})
    result = registry.execute("append", {"path": "f.txt", "content": ""})
    assert result.get("changed") is False
    assert (tmp_path / "f.txt").read_text() == "one\n"


def test_append_directory_rejected(tmp_path: Path):
    _, registry = _make_tools(tmp_path)
    (tmp_path / "sub").mkdir()
    with pytest.raises(IsADirectoryError):
        registry.execute("append", {"path": "sub", "content": "x"})


# ── 11: append counts as mutation ────────────────────────────────────────────

def test_append_counts_as_mutation():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(
                tool_calls=[_call(2, "append", path="notes-out.md", content="more\n")],
                usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], task="Create notes-out.md", event=events.append)
        result = agent.run()
        assert result.status == "completed"
        assert result.changed_paths == ["notes-out.md"]
        assert result.metrics["first_mutation_turn"] == 1
        assert result.metrics["tool_calls"] == 2
        assert not any(e.kind == "no_progress" for e in events)


# ── 12: append security ──────────────────────────────────────────────────────

def test_append_workspace_escape_rejected(tmp_path: Path):
    _, registry = _make_tools(tmp_path)
    with pytest.raises(PermissionError):
        registry.execute("append", {"path": "../escape.txt", "content": "x"})
    with pytest.raises(PermissionError):
        registry.execute("append", {"path": "/tmp/escape.txt", "content": "x"})


# ── 13: read-only ────────────────────────────────────────────────────────────

def test_append_denied_without_write_capability(tmp_path: Path):
    tools = CodingTools(tmp_path, ToolPolicy(Capabilities(write=False)), tmp_path / ".logs")
    registry = ToolRegistry(tools)
    names = {s["function"]["name"] for s in registry.schemas()}
    assert "append" not in names
    with pytest.raises(PermissionError):
        registry.execute("append", {"path": "a.txt", "content": "x"})


# ── 14: repair precedence ────────────────────────────────────────────────────

def test_targeted_repair_schema_unchanged():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "write", path="index.html", content="x")],
                          usage=Usage(90, 20)),
            ModelResponse(content="done-ish", usage=Usage(70, 10)),
            ModelResponse(tool_calls=[_call(2, "edit", path="index.html",
                                            edits=[{"old": "x", "new": "y"}])],
                          usage=Usage(90, 20)),
            ModelResponse(content="fixed", usage=Usage(70, 10)),
        ], task="Build a responsive landing page")
        agent.run()
        # Find a repair-turn request: targeted set has no write/append/bash.
        repair_requests = [
            r for r in agent.runtime.requests
            if _tool_names(r) == {"read", "grep", "edit"}
        ]
        assert repair_requests, "expected a targeted-repair turn without append"


# ── 16: boundary regression ──────────────────────────────────────────────────

def test_three_pre_mutation_calls_still_trigger_boundary():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/MISSING.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "bash", argv=["find", ".", "-name", "*.md"])],
                          usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(4, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        assert agent.run().status == "completed"
        entered = [e for e in events if e.kind == "implementation_phase_entered"]
        assert len(entered) == 1
        assert entered[0].data["reason"] == "pre_mutation_tool_limit"
        # (Case 15: existing v4 repair suite stays green — covered by the
        # full-suite run; see test_harness_v4_repair.py.)
