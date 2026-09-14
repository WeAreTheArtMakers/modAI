from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from modai.core.context import ContextManager
from modai.core.harness import CodingHarness
from modai.core.session import SessionStore
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.orchestration.router import TaskRouter
from modai.tools.coding import CodingTools
from modai.tools.policy import Capabilities, ToolPolicy
from modai.tools.registry import ToolRegistry


def call(number: int, name: str, **arguments):
    return ToolCall(f"call-{number}", name, arguments)


def harness(root: Path, responses, task="Create notes.txt with a completed result.", **kwargs):
    return CodingHarness(runtime=ScriptedRuntime(responses), workspace=root,
                         run_dir=root / ".run", task=task, **kwargs)


def test_single_session_writes_and_verifies_artifact():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        agent = harness(root, [
            ModelResponse(tool_calls=[call(1, "write", path="notes.txt", content="done\n")], usage=Usage(10, 3)),
            ModelResponse(content="Implemented and checked.", usage=Usage(12, 5)),
        ])
        result = agent.run()
        assert result.status == "completed"
        assert (root / "notes.txt").read_text() == "done\n"
        assert result.turns == 2
        assert len(agent.runtime.requests) == 2


def test_precise_edit_is_atomic_on_mismatch_and_preserves_crlf_and_bom():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        target = root / "a.txt"
        target.write_bytes(b"\xef\xbb\xbfalpha\r\nbeta\r\n")
        tools = CodingTools(root, ToolPolicy(Capabilities(write=True)), root / ".logs")
        original = target.read_bytes()
        with pytest.raises(ValueError):
            tools.edit("a.txt", [{"old": "alpha", "new": "A"}, {"old": "missing", "new": "M"}])
        assert target.read_bytes() == original
        result = tools.edit("a.txt", [{"old": "alpha", "new": "A"}, {"old": "beta", "new": "B"}])
        assert result["changed"] is True
        assert target.read_bytes() == b"\xef\xbb\xbfA\r\nB\r\n"


def test_file_evidence_cache_uses_content_hash_and_invalidates_after_edit():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "a.txt").write_text("one")
        tools = CodingTools(root, ToolPolicy(Capabilities(write=True)), root / ".logs")
        registry = ToolRegistry(tools)
        assert "cached" not in registry.execute("read", {"path": "a.txt"})
        assert registry.execute("read", {"path": "a.txt"})["cached"] is True
        registry.execute("edit", {"path": "a.txt", "edits": [{"old": "one", "new": "two"}]})
        assert "cached" not in registry.execute("read", {"path": "a.txt"})


def test_read_only_policy_removes_mutation_tools_and_rejects_mutating_git():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        tools = CodingTools(root, ToolPolicy(Capabilities(write=False)), root / ".logs")
        names = {item["function"]["name"] for item in ToolRegistry(tools).schemas()}
        assert "write" not in names and "edit" not in names
        with pytest.raises(PermissionError):
            tools.bash(["git", "reset", "--hard"])


def test_read_only_analysis_can_finish_without_a_file_mutation():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        agent = harness(root, [ModelResponse(content="Review: no defects found.")],
                        task="Read-only review of this empty fixture", write_allowed=False)
        result = agent.run()
        assert result.status == "completed"
        assert result.verification["checks"][0]["name"] == "read_only_analysis"


def test_truncated_tool_batch_is_never_executed():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        agent = harness(root, [
            ModelResponse(tool_calls=[call(1, "write", path="bad.txt", content="bad")], truncated=True),
            ModelResponse(tool_calls=[call(2, "write", path="good.txt", content="good")]),
            ModelResponse(content="done"),
        ])
        result = agent.run()
        assert result.status == "completed"
        assert not (root / "bad.txt").exists()
        assert (root / "good.txt").exists()


def test_no_progress_guard_steers_repeated_read_batches():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "seed.txt").write_text("seed")
        events = []
        responses = [ModelResponse(tool_calls=[call(i, "read", path="seed.txt")]) for i in range(1, 4)]
        responses += [ModelResponse(tool_calls=[call(4, "write", path="result.txt", content="ok")]), ModelResponse(content="done")]
        agent = harness(root, responses, event=events.append)
        assert agent.run().status == "completed"
        assert any(item.kind == "no_progress" for item in events)
        assert "NO-PROGRESS GUARD" in json.dumps(agent.runtime.requests, ensure_ascii=False)


def test_resume_uses_same_jsonl_transcript():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        first = harness(root, [ModelResponse(tool_calls=[call(1, "write", path="resume.txt", content="kept")])], max_turns=1)
        assert first.run().status == "needs_attention"
        second = harness(root, [ModelResponse(content="resumed and complete")])
        second.coding_tools.mutated_paths.add("resume.txt")
        result = second.run(resume=True)
        assert result.status == "completed"
        assert len(second.runtime.requests[0]["messages"]) >= 4


def test_session_control_queues_are_safe_and_fifo():
    with tempfile.TemporaryDirectory() as directory:
        store = SessionStore(Path(directory))
        store.steer("first"); store.steer("second"); store.follow_up("later")
        assert store.take_steering() == ["first", "second"]
        assert store.take_steering() == []
        assert store.take_follow_up() == "later"
        store.abort()
        assert store.aborted


def test_compaction_keeps_objective_and_complete_tool_pair():
    manager = ContextManager(250, 64)
    messages = [{"role": "system", "content": "system"}, {"role": "user", "content": "objective"}]
    messages += [{"role": "user", "content": "x" * 100} for _ in range(8)]
    messages += [{"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "read"}}]},
                 {"role": "tool", "tool_call_id": "a", "content": "result"},
                 {"role": "tool", "tool_call_id": "orphan", "content": "orphan"}]
    compacted = manager.compact(messages)
    assert compacted[0]["content"] == "system"
    assert compacted[1]["content"] == "objective"
    assert "orphan" not in json.dumps(compacted)


def test_router_strongly_prefers_solo_for_software_and_honors_explicit_mode():
    router = TaskRouter()
    assert router.route("Build and test a responsive landing page", "auto").mode == "solo"
    assert router.route("Build a page", "orchestra").mode == "orchestra"


def test_orchestra_delegate_is_bounded_and_read_only_then_main_coder_writes():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "source.txt").write_text("evidence")
        responses = [
            ModelResponse(tool_calls=[call(1, "delegate", task="Inspect source.txt", focus="content")]),
            ModelResponse(tool_calls=[call(2, "read", path="source.txt")]),
            ModelResponse(content="source.txt contains evidence"),
            ModelResponse(tool_calls=[call(3, "write", path="result.txt", content="evidence used\n")]),
            ModelResponse(content="done"),
        ]
        agent = harness(root, responses, task="Create result.txt after an independent inspection",
                        delegate_enabled=True)
        result = agent.run()
        assert result.status == "completed"
        assert (root / "result.txt").read_text() == "evidence used\n"
        delegate_request = agent.runtime.requests[1]
        delegate_tools = {item["function"]["name"] for item in delegate_request["tools"]}
        assert "write" not in delegate_tools and "edit" not in delegate_tools


def test_cloud_delegate_usage_is_separate_while_writer_stays_local():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        main = ScriptedRuntime([
            ModelResponse(tool_calls=[call(1, "delegate", task="Public comparison")], usage=Usage(10, 2)),
            ModelResponse(tool_calls=[call(2, "write", path="report.md", content="# Result\n")], usage=Usage(12, 3)),
            ModelResponse(content="done", usage=Usage(8, 2)),
        ])
        main.provider = "local"
        cloud = ScriptedRuntime([ModelResponse(content="public evidence", usage=Usage(100, 20))])
        cloud.provider = "cloud"
        agent = CodingHarness(runtime=main, delegate_runtime=cloud, delegate_enabled=True,
                              workspace=root, run_dir=root / ".run", task="Create report.md")
        result = agent.run()
        assert result.status == "completed"
        assert result.usage["local_tokens"] == 37
        assert result.usage["cloud_tokens"] == 120


def test_static_site_e2e_fixture_reaches_browser_gate():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        html = """<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>MODAI</title><link rel='stylesheet' href='styles.css'></head><body><main><h1>MODAI</h1><p>Local coding harness.</p></main><script src='app.js'></script></body></html>"""
        responses = [
            ModelResponse(tool_calls=[call(1, "write", path="index.html", content=html)]),
            ModelResponse(tool_calls=[call(2, "write", path="styles.css", content="*{box-sizing:border-box}body{margin:0;max-width:100%;font-family:sans-serif}main{padding:2rem}")]),
            ModelResponse(tool_calls=[call(3, "write", path="app.js", content="document.documentElement.dataset.ready='true';\n")]),
            ModelResponse(content="site complete"),
        ]
        result = harness(root, responses, task="Build a responsive landing page").run()
        assert result.status == "completed"
        assert {item["name"]: item["verdict"] for item in result.verification["checks"]} == {
            "artifact_contract": "PASS", "static_site": "PASS", "browser_quality": "PASS"
        }


def test_static_site_repair_uses_latest_failure_in_same_session():
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        broken = "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>X</title></head><body><main><h1>X</h1></main></body></html>"
        fixed = broken.replace("<title>", "<meta name='viewport' content='width=device-width,initial-scale=1'><title>")
        responses = [ModelResponse(tool_calls=[call(1, "write", path="index.html", content=broken)]),
                     ModelResponse(content="done"),
                     ModelResponse(tool_calls=[call(2, "edit", path="index.html", edits=[{"old": broken, "new": fixed}])]),
                     ModelResponse(content="fixed")]
        agent = harness(root, responses, task="Build a responsive HTML landing page")
        result = agent.run()
        assert result.status == "completed"
        assert result.verification["sequence"] == 2
        assert "responsive viewport" in json.dumps(agent.runtime.requests, ensure_ascii=False)
