"""V4.1 pre-mutation reliability regression tests.

The preserved benchmark trace showed the run dying BEFORE repair:
  - failed reads consumed exploration budget,
  - read stayed open after budget exhaustion (hallucinated-path loop),
  - RemoteProtocolError was classified transient=False (no recovery).

Repair code is untouched here; these tests lock pre-mutation behavior only.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.quality.project import project_snapshot
from modai.tools.coding import CodingTools
from modai.tools.policy import Capabilities, ToolPolicy


class RemoteProtocolError(Exception):
    pass


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


# ── 1: failed reads cost no budget ───────────────────────────────────────────

def test_failed_read_does_not_consume_discovery_budget():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/MISSING.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        result = agent.run()

        assert result.status == "completed", f"got {result.status}: {result.final}"
        # 1 success + 1 failure must NOT exhaust the 2-success budget:
        # turn 3 still sees the full schema (bash available).
        assert "bash" in _tool_names(agent.runtime.requests[2]), (
            f"failed read consumed budget: {sorted(_tool_names(agent.runtime.requests[2]))}"
        )
        assert "IMPLEMENTATION PHASE" not in json.dumps(agent.runtime.requests, ensure_ascii=False)


# ── 2: two successes -> write-only bootstrap ──────────────────────────────────

def test_two_successful_discovery_calls_switch_to_mutation_only_tools():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "ls", path=".")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        result = agent.run()

        assert result.status == "completed"
        assert _tool_names(agent.runtime.requests[2]) == {"write"}, (
            f"expected implementation-only tools, got {sorted(_tool_names(agent.runtime.requests[2]))}"
        )


# ── 3: missing-path loop cannot run forever ──────────────────────────────────

def test_missing_paths_cannot_loop_indefinitely():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="docs/NOPE-A.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="docs/NOPE-B.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ])
        result = agent.run()

        assert result.status == "completed", f"got {result.status}: {result.final}"
        # Two consecutive PATH_NOT_FOUND closes discovery even with 0 successes.
        assert _tool_names(agent.runtime.requests[2]) == {"write"}

        history = json.dumps(agent.runtime.requests, ensure_ascii=False)
        assert "PATH_NOT_FOUND" in history
        assert "retryable" in history
        # Guidance points at the real tree, never at internals.
        assert "README.md" in history
        assert ".benchmark_run" not in history


# ── 4: harness internals hidden from discovery ───────────────────────────────

def test_internal_benchmark_paths_are_hidden():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        (root / ".benchmark_run" / "logs").mkdir(parents=True)
        (root / ".benchmark_run" / "logs" / "x.txt").write_text("log")
        (root / ".modai" / "browser").mkdir(parents=True)
        (root / ".modai" / "browser" / "y.png").write_bytes(b"img")

        snapshot = project_snapshot(root)
        assert "README.md" in snapshot
        assert ".benchmark_run" not in snapshot
        assert ".modai" not in snapshot

        tools = CodingTools(root, ToolPolicy(Capabilities(write=True)), root / ".logs")
        entries = tools.ls(".", depth=3)["entries"]
        assert any("README.md" in e for e in entries)
        assert not any(".benchmark_run" in e or ".modai" in e for e in entries)

        matches = tools.find("*", ".")["matches"]
        assert not any(".benchmark_run" in m or ".modai" in m for m in matches)


# ── 5: chunked-read teardown is transient ────────────────────────────────────

def test_incomplete_chunked_read_is_transient():
    exc = RemoteProtocolError(
        "peer closed connection without sending complete message body "
        "(incomplete chunked read)"
    )
    assert CodingHarness._transient_model_error(exc) is True
    assert CodingHarness._transient_model_error(ValueError("boom")) is False


# ── 6: transport retry recovers with reduced context ─────────────────────────

def test_transport_retry_uses_reduced_context():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            RemoteProtocolError(
                "peer closed connection without sending complete message body "
                "(incomplete chunked read)"
            ),
            ModelResponse(tool_calls=[_call(1, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], model_retries=1, event=events.append)
        result = agent.run()

        assert result.status == "completed", f"got {result.status}: {result.final}"
        assert agent.runtime.requests[0]["_reduced_context"] is False
        assert agent.runtime.requests[1]["_reduced_context"] is True
        assert any(e.kind == "model_retry" for e in events)


# ── 7: implementation nudge after budget ─────────────────────────────────────

def test_after_exploration_budget_read_is_not_in_schema():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "grep", pattern="MODAI", path=".")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        result = agent.run()

        assert result.status == "completed"
        names = _tool_names(agent.runtime.requests[2])
        assert "read" not in names and "write" in names

        history = json.dumps(agent.runtime.requests, ensure_ascii=False)
        assert "IMPLEMENTATION PHASE" in history
        budget_events = [e for e in events if e.kind == "exploration_budget_exhausted"]
        assert len(budget_events) == 1
