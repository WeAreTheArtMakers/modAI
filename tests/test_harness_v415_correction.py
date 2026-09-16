"""V4.1.5 completed-oversize correction regression tests.

The rescue micro-context can still return a COMPLETED write that overshoots
the hard limit (real trace: 4798 chars). Exactly ONE size-correction pass
retries with a smaller fresh context; the rejected content is never fed back.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime


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


def _empty_truncated() -> ModelResponse:
    return ModelResponse(content="", tool_calls=[], usage=Usage(60, 2048),
                         stop_reason="length", truncated=True)


def _tool_names(request) -> set[str]:
    return {t["function"]["name"] for t in (request.get("tools") or [])}


def _seed(root: Path) -> None:
    (root / "README.md").write_text("# MODAI\nLocal coding harness.\n")


def _correction_script(rescue_len: int = 4798, correction: dict | None = None) -> list:
    correction = correction or {"path": "notes-out.md", "content": "# small\n"}
    return [
        ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
        ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
        _empty_truncated(),
        ModelResponse(tool_calls=[_call(9, "write", path="notes-out.md",
                                        content="x" * rescue_len)], usage=Usage(200, 100)),
        ModelResponse(tool_calls=[_call(10, "write", **correction)], usage=Usage(90, 20)),
        ModelResponse(content="Done.", usage=Usage(70, 10)),
    ]


def _correction_request(agent: CodingHarness) -> dict:
    # requests: [read, read, empty, rescue, correction, post, ...]
    assert len(agent.runtime.requests) >= 5
    return agent.runtime.requests[4]


# ── 1: correction triggered exactly once ─────────────────────────────────────

def test_size_correction_triggered_exactly_once():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, _correction_script(), event=events.append)
        assert agent.run().status == "completed"
        corrections = [e for e in events if e.kind == "bootstrap_size_correction"]
        attempted = [e for e in corrections if e.data.get("outcome") == "attempted"]
        assert len(attempted) == 1
        assert attempted[0].data["actual_chars"] == 4798
        assert attempted[0].data["hard_max"] == 4000


# ── 2: correction tools write-only ───────────────────────────────────────────

def test_correction_request_is_write_only():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _correction_script())
        assert agent.run().status == "completed"
        assert _tool_names(_correction_request(agent)) == {"write"}


# ── 3+4: fresh context with size numbers, rejected content excluded ──────────

def test_correction_context_has_numbers_not_content():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _correction_script())
        assert agent.run().status == "completed"
        text = json.dumps(_correction_request(agent)["messages"], ensure_ascii=False)
        assert "4798" in text and "4000" in text and "2000" in text
        assert "BOOTSTRAP SIZE CORRECTION" in text
        assert "IMPLEMENTATION PHASE" not in text
        assert "x" * 1000 not in text, "rejected content leaked into correction"
        assert "Local coding harness" not in text, "evidence re-fed into correction"


# ── 5: correction success records mutation + restores surface ────────────────

def test_correction_success_restores_normal_surface():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _correction_script())
        result = agent.run()
        assert result.status == "completed"
        assert (root / "notes-out.md").read_text() == "# small\n"
        assert result.metrics["first_mutation_turn"] == 3
        assert result.metrics["bootstrap_size_corrections"] == 1
        assert result.metrics["bootstrap_oversize_chars"] == 4798
        names = _tool_names(agent.runtime.requests[5])
        assert {"read", "bash", "append", "write", "edit"} <= names


# ── 6: second oversize fails fast ────────────────────────────────────────────

def test_second_oversize_fails_fast():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, _correction_script(
            correction={"path": "notes-out.md", "content": "y" * 4500}), event=events.append)
        result = agent.run()
        assert result.status == "needs_attention"
        assert len(agent.runtime.requests) == 5, "must not attempt a third write"
        assert not (root / "notes-out.md").exists()
        corrections = [e for e in events if e.kind == "bootstrap_size_correction"]
        assert len([e for e in corrections if e.data.get("outcome") == "attempted"]) == 1


# ── 7: normal coding oversize never enters correction ────────────────────────

def test_normal_coding_oversize_never_corrects():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(tool_calls=[_call(2, "write", path="other.md", content="z" * 5000)],
                          usage=Usage(200, 100)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        result = agent.run()
        assert result.status == "completed"
        assert not (root / "other.md").exists()
        assert not [e for e in events if e.kind in ("bootstrap_rescue", "bootstrap_size_correction")]


# ── 8: repair never enters correction ────────────────────────────────────────

def test_repair_never_enters_correction():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        broken = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                  "<title>X</title></head><body><main><h1>X</h1></main></body></html>")
        fixed = broken.replace("<title>", "<meta name='viewport' content='width=device-width,initial-scale=1'><title>")
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "write", path="index.html", content=broken)],
                          usage=Usage(100, 30)),
            ModelResponse(content="Done.", usage=Usage(80, 15)),
            ModelResponse(tool_calls=[_call(2, "edit", path="index.html",
                                            edits=[{"old": broken, "new": fixed}])],
                          usage=Usage(110, 25)),
            ModelResponse(content="Fixed.", usage=Usage(80, 15)),
        ], task="Build a responsive HTML landing page", event=events.append)
        assert agent.run().status == "completed"
        assert not [e for e in events if e.kind in ("bootstrap_rescue", "bootstrap_size_correction")]
