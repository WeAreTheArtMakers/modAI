"""V4.1.1 hard pre-mutation boundary regression tests.

Real-model trace showed exploration bypass via bash tool-switching:
read/read-fail/bash-find/bash-find/ls with zero mutations. Repair code is
untouched; these tests lock the hard boundary only:

  at most 3 pre-mutation tool calls of ANY kind -> next schema is
  exactly {write} (bootstrap) until the first successful mutation.
"""
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.quality.project import project_snapshot


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


# ── 1: hard limit across tool types ──────────────────────────────────────────

def test_hard_limit_forces_implementation_only_schema():
    """read-ok + read-fail + bash -> turn 4 schema is exactly {write} (bootstrap)."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/MISSING.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "bash", argv=["find", ".", "-name", "*.md"])],
                          usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(4, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        result = agent.run()

        assert result.status == "completed", f"got {result.status}: {result.final}"
        assert _tool_names(agent.runtime.requests[3]) == {"write"}, (
            f"turn 4 must be implementation-only, got {sorted(_tool_names(agent.runtime.requests[3]))}"
        )


# ── 2: failures count toward the limit ───────────────────────────────────────

def test_hard_limit_counts_failures_too():
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
        result = agent.run()

        assert result.status == "completed"
        entered = [e for e in events if e.kind == "implementation_phase_entered"]
        assert len(entered) == 1
        assert entered[0].data["reason"] == "pre_mutation_tool_limit"
        assert entered[0].data["pre_mutation_tool_calls"] == 3
        assert entered[0].data["discovery_successes"] == 1


# ── 3: event emitted exactly once ────────────────────────────────────────────

def test_implementation_phase_event_emitted_once():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "ls", path=".")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        assert agent.run().status == "completed"
        entered = [e for e in events if e.kind == "implementation_phase_entered"]
        assert len(entered) == 1, f"expected exactly one event, got {len(entered)}"
        assert entered[0].data["reason"] == "discovery_budget"


# ── 4: reason recorded for path-not-found cutoff ─────────────────────────────

def test_implementation_phase_reason_path_not_found():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="docs/NOPE-A.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/NOPE-B.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        assert agent.run().status == "completed"
        entered = [e for e in events if e.kind == "implementation_phase_entered"]
        assert len(entered) == 1
        assert entered[0].data["reason"] == "path_not_found_limit"


# ── 5: reset after first mutation ────────────────────────────────────────────

def test_normal_schema_returns_after_first_mutation():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/MISSING.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "bash", argv=["find", ".", "-name", "*.md"])],
                          usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(4, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        assert agent.run().status == "completed"
        # Turn 5 (final) is built after the mutation: full schema again.
        assert "bash" in _tool_names(agent.runtime.requests[4])
        assert "read" in _tool_names(agent.runtime.requests[4])


# ── 6: repair precedence over implementation-only ────────────────────────────

def test_repair_mode_takes_precedence_over_implementation_boundary():
    """Forced implementation + zero-mutation final -> repair schema wins."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(content="Done with nothing.", usage=Usage(70, 10)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
        ])
        result = agent.run()

        assert result.status == "completed", f"got {result.status}: {result.final}"
        # Turn 4 is a structural repair turn (missing notes-out.md): write kept.
        repair_tools = _tool_names(agent.runtime.requests[3])
        assert repair_tools == {"read", "grep", "edit", "write"}, (
            f"repair schema must win, got {sorted(repair_tools)}"
        )


# ── 7: telemetry in harness metrics ──────────────────────────────────────────

def test_pre_mutation_telemetry_in_metrics():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/MISSING.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "bash", argv=["find", ".", "-name", "*.md"])],
                          usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(4, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        result = agent.run()
        assert result.status == "completed"
        assert result.metrics["pre_mutation_tool_calls"] == 3
        assert result.metrics["discovery_successes"] == 1
        assert result.metrics["path_not_found_count"] == 1
        assert result.metrics["implementation_phase_entered"] is True
        assert result.metrics["implementation_phase_reason"] == "pre_mutation_tool_limit"


# ── 8: benchmark isolation ───────────────────────────────────────────────────

def _load_benchmark_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "benchmark_landing_page.py"
    spec = importlib.util.spec_from_file_location("benchmark_landing_page", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_benchmark_trace_lives_outside_workspace():
    module = _load_benchmark_module()
    with tempfile.TemporaryDirectory() as d:
        ws = Path(d) / "proj"
        ws.mkdir()
        (ws / "README.md").write_text("# fixture\n")
        trace = module.resolve_trace_dir(ws)

        assert trace != ws and ws not in trace.parents, f"trace {trace} inside workspace {ws}"
        assert trace.parent == ws.parent
        trace.mkdir(parents=True, exist_ok=True)
        (trace / "session.jsonl").write_text("{}\n")
        (trace / "benchmark_result.json").write_text("{}\n")

        snapshot = project_snapshot(ws)
        assert "README.md" in snapshot
        assert ".benchmark_run" not in snapshot
        assert "session.jsonl" not in snapshot
        assert "benchmark_result.json" not in snapshot

        physical = {p.name for p in ws.rglob("*")}
        assert "session.jsonl" not in physical
        assert "benchmark_result.json" not in physical


# ── v4.1.2: incremental-write guidance + emission telemetry ──────────────────

def test_implementation_nudge_steers_incremental_writes():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "README.md").write_text("# MODAI\n")
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        assert agent.run().status == "completed"
        history = json.dumps(agent.runtime.requests, ensure_ascii=False)
        assert "bounded write/append/edit" in history
        assert "oversized tool call" in history


def test_empty_response_event_carries_emission_telemetry():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "README.md").write_text("# MODAI\n")
        events: list = []
        agent = _harness(root, [
            ModelResponse(content="", tool_calls=[], usage=Usage(100, 2048),
                          stop_reason="length", truncated=True),
            ModelResponse(tool_calls=[_call(1, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        assert agent.run().status == "completed"
        empties = [e for e in events if e.kind == "empty_model_response"]
        assert len(empties) == 1
        data = empties[0].data
        assert data["truncated"] is True
        assert data["stop_reason"] == "length"
        assert data["output_tokens"] == 2048
        assert data["content_length"] == 0
