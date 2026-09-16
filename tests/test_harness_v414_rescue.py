"""V4.1.4 truncation-aware bootstrap rescue regression tests.

A length-truncated empty response while waiting for the FIRST mutation means
the model tried to emit the whole task at once. Retrying the identical context
has zero information value, so ONE fresh micro-context asks only for a small
bounded scaffold write. A second truncation fails fast (no 833s death loop).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.tools.coding import BOOTSTRAP_WRITE_TARGET_CHARS, MODEL_WRITE_MAX_CHARS, CodingTools
from modai.tools.policy import Capabilities, ToolPolicy
from modai.tools.registry import ToolRegistry


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


def _seed(root: Path, size: int = 60) -> None:
    (root / "README.md").write_text("# MODAI\nLocal coding harness.\n" + "x\n" * size)


def _bootstrap_script(small_write: dict | None = None) -> list:
    """read, read -> force; empty truncated -> rescue; then scripted rescue write."""
    write_args = small_write or {"path": "notes-out.md", "content": "# out\n"}
    return [
        ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
        ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
        _empty_truncated(),
        ModelResponse(tool_calls=[_call(9, "write", **write_args)], usage=Usage(90, 20)),
        ModelResponse(content="Done.", usage=Usage(70, 10)),
    ]


def _rescue_request(agent: CodingHarness) -> dict:
    # requests: [read, read, empty-turn, rescue, post-rescue, ...]
    assert len(agent.runtime.requests) >= 4
    return agent.runtime.requests[3]


# ── 1: rescue instead of generic retry ───────────────────────────────────────

def test_truncated_bootstrap_triggers_rescue():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, _bootstrap_script(), event=events.append)
        assert agent.run().status == "completed"
        outcomes = [e.data.get("outcome") for e in events if e.kind == "bootstrap_rescue"]
        assert "attempted" in outcomes and "succeeded" in outcomes


# ── 2: rescue tools write-only ───────────────────────────────────────────────

def test_rescue_request_is_write_only_with_tighter_cap():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _bootstrap_script())
        assert agent.run().status == "completed"
        req = _rescue_request(agent)
        assert _tool_names(req) == {"write"}
        content_prop = req["tools"][0]["function"]["parameters"]["properties"]["content"]
        assert content_prop["maxLength"] == MODEL_WRITE_MAX_CHARS == 4000
        assert "2500" in content_prop.get("description", "")


# ── 3: no discovery history carried ──────────────────────────────────────────

def test_rescue_request_carries_no_session_history():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root, size=400)  # ~1KB README; history would be far bigger
        agent = _harness(root, _bootstrap_script())
        assert agent.run().status == "completed"
        text = json.dumps(_rescue_request(agent)["messages"], ensure_ascii=False)
        assert "IMPLEMENTATION PHASE" not in text
        assert "PATH_NOT_FOUND" not in text
        assert len(text) < 6000


# ── 4: objective preserved ───────────────────────────────────────────────────

def test_rescue_preserves_original_objective():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        task = "Read README.md and write notes-out.md"
        agent = _harness(root, _bootstrap_script(), task=task)
        assert agent.run().status == "completed"
        text = json.dumps(_rescue_request(agent)["messages"], ensure_ascii=False)
        assert task in text
        assert "CURRENT SUBTASK" in text


# ── 5: evidence bounded ──────────────────────────────────────────────────────

def test_rescue_evidence_is_clipped():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root, size=2000)  # ~4KB README forces clipping
        agent = _harness(root, _bootstrap_script())
        assert agent.run().status == "completed"
        facts = next(
            m["content"] for m in _rescue_request(agent)["messages"]
            if m.get("role") == "user" and "KNOWN PRODUCT FACTS" in m.get("content", "")
        )
        assert len(facts) <= 2500 + 200, f"evidence not clipped: {len(facts)}"


# ── 6+7: merge + first_mutation_turn ─────────────────────────────────────────

def test_rescue_merge_and_mutation_turn():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _bootstrap_script({"path": "notes-out.md",
                                                  "content": "# rescued\n"}))
        result = agent.run()
        assert result.status == "completed"
        assert (root / "notes-out.md").read_text() == "# rescued\n"
        assert result.metrics["first_mutation_turn"] == 3
        post = agent.runtime.requests[4]["messages"]
        assistants = [m for m in post if m.get("role") == "assistant" and m.get("tool_calls")]
        assert any(tc["function"]["name"] == "write" for m in assistants for tc in m["tool_calls"])
        tools = [m for m in post if m.get("role") == "tool"]
        assert any("notes-out.md" in str(m.get("content", "")) for m in tools)


# ── 8: normal surface after rescue ───────────────────────────────────────────

def test_normal_surface_returns_after_rescue():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _bootstrap_script())
        assert agent.run().status == "completed"
        names = _tool_names(agent.runtime.requests[4])
        assert {"read", "bash", "append", "write", "edit"} <= names


# ── 9: second truncation fails fast ──────────────────────────────────────────

def test_second_truncation_fails_fast():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            _empty_truncated(),
            _empty_truncated(),  # rescue attempt also truncated
        ], event=events.append)
        result = agent.run()
        assert result.status == "needs_attention"
        assert len(agent.runtime.requests) == 4, "must not retry after failed rescue"
        assert not (root / "notes-out.md").exists()
        outcomes = [e.data.get("outcome") for e in events if e.kind == "bootstrap_rescue"]
        assert outcomes.count("attempted") == 1


# ── 10: never in repair mode ─────────────────────────────────────────────────

def test_rescue_never_triggers_in_repair_mode():
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
            _empty_truncated(),  # truncated empty DURING repair -> generic path
            ModelResponse(tool_calls=[_call(2, "edit", path="index.html",
                                            edits=[{"old": broken, "new": fixed}])],
                          usage=Usage(110, 25)),
            ModelResponse(content="Fixed.", usage=Usage(80, 15)),
        ], task="Build a responsive HTML landing page", event=events.append)
        assert agent.run().status == "completed"
        assert not [e for e in events if e.kind == "bootstrap_rescue"]


# ── 11: transport uses retry, not rescue ─────────────────────────────────────

def test_transport_error_uses_retry_not_rescue():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            TimeoutError("timed out"),
            ModelResponse(tool_calls=[_call(2, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], model_retries=1, event=events.append)
        assert agent.run().status == "completed"
        assert not [e for e in events if e.kind == "bootstrap_rescue"]
        assert any(e.kind == "model_retry" for e in events)


# ── 12: non-length empty keeps existing policy ───────────────────────────────

def test_non_length_empty_keeps_existing_policy():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        events: list = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(tool_calls=[_call(2, "read", path="README.md")], usage=Usage(60, 8)),
            ModelResponse(content="", tool_calls=[], usage=Usage(60, 8)),  # not truncated
            ModelResponse(tool_calls=[_call(3, "write", path="notes-out.md", content="# out\n")],
                          usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append)
        assert agent.run().status == "completed"
        assert not [e for e in events if e.kind == "bootstrap_rescue"]
        # Bootstrap still holds: post-empty turn remains write-only.
        assert _tool_names(agent.runtime.requests[3]) == {"write"}


# ── contract alignment: target vs hard limit ─────────────────────────────────

def test_contract_constants():
    assert MODEL_WRITE_MAX_CHARS == 4000
    assert BOOTSTRAP_WRITE_TARGET_CHARS == 2500


def test_rescue_prompt_states_target_and_hard_limit():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        _seed(root)
        agent = _harness(root, _bootstrap_script())
        assert agent.run().status == "completed"
        subtask = next(
            m["content"] for m in _rescue_request(agent)["messages"]
            if m.get("role") == "user" and "CURRENT SUBTASK" in m.get("content", "")
        )
        assert "2500" in subtask and "4000" in subtask


def _make_rescue_registry(root: Path) -> tuple:
    tools = CodingTools(root, ToolPolicy(Capabilities(write=True)), root / ".logs")
    return tools, ToolRegistry(tools)


def test_realistic_bootstrap_size_accepted(tmp_path: Path):
    tools, registry = _make_rescue_registry(tmp_path)
    result = registry.execute("write", {"path": "b.txt", "content": "x" * 3089})
    assert result["changed"] is True
    assert (tmp_path / "b.txt").stat().st_size == 3089


def test_hard_limit_boundary_4000_4001(tmp_path: Path):
    _, registry = _make_rescue_registry(tmp_path)
    assert registry.execute("write", {"path": "ok.txt", "content": "y" * 4000})["changed"] is True
    rejected = registry.execute("write", {"path": "no.txt", "content": "y" * 4001})
    assert rejected.get("error_code") == "CONTENT_TOO_LARGE"
    assert not (tmp_path / "no.txt").exists()


def test_append_contract_uses_hard_limit(tmp_path: Path):
    from modai.tools.registry import SCHEMAS

    tools, registry = _make_rescue_registry(tmp_path)
    content_prop = next(s for s in SCHEMAS if s["function"]["name"] == "append")
    content_prop = content_prop["function"]["parameters"]["properties"]["content"]
    assert content_prop["maxLength"] == MODEL_WRITE_MAX_CHARS == 4000
    registry.execute("write", {"path": "f.txt", "content": "one\n"})
    result = registry.execute("append", {"path": "f.txt", "content": "z" * 4000})
    assert result["changed"] is True
