"""Mocked Ollama native-tool rejection and bounded JSON compatibility regressions."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from ollama import ResponseError

from modai.core.evidence import SharedEvidenceCache
from modai.core.harness import CodingHarness
from modai.models.ollama import OllamaRuntime, ToolCompatibilityError
from modai.orchestration.coordinator import AdaptiveOrchestra
from modai.orchestration.delegation import ReadOnlyDelegate
from modai.orchestration.scheduler import LocalInferenceScheduler, ResourceSnapshot
from modai.tools.registry import SCHEMAS


READ = next(schema for schema in SCHEMAS if schema["function"]["name"] == "read")
WRITE = next(schema for schema in SCHEMAS if schema["function"]["name"] == "write")
UNSUPPORTED = "registry.ollama.ai/library/gemma3:4b does not support tools"


def _reply(content: str) -> dict:
    return {"message": {"content": content}, "prompt_eval_count": 8, "eval_count": 5}


class Client:
    def __init__(self, replies: list, capabilities=None):
        self.replies = list(replies)
        self.capabilities = capabilities
        self.calls: list[dict] = []
        self.shows = 0

    def show(self, model: str):
        self.shows += 1
        return {"capabilities": self.capabilities} if self.capabilities is not None else {}

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        result = self.replies.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _runtime(client: Client) -> OllamaRuntime:
    return OllamaRuntime(client, "gemma3:4b")


def test_native_tool_capable_stream_preserves_streaming_and_usage():
    client = Client([iter([
        _reply("Looking "),
        {"message": {"content": "now", "tool_calls": [{"function": {
            "name": "read", "arguments": {"path": "README.md"}}}]},
         "prompt_eval_count": 20, "eval_count": 6},
    ])], capabilities=["completion", "tools"])
    chunks: list[str] = []
    response = _runtime(client).generate([], [READ], on_text=chunks.append)
    assert client.calls[0]["tools"] == [READ] and client.calls[0]["stream"] is True
    assert response.tool_calls[0].name == "read"
    assert response.usage.total_tokens == 26
    assert chunks == ["Looking ", "now"]
    assert client.shows == 1


@pytest.mark.parametrize("lazy", [False, True])
def test_immediate_or_lazy_unsupported_tools_uses_validated_fallback(lazy: bool):
    error = ResponseError(UNSUPPORTED, 400)
    def failure():
        raise error
        yield  # make the rejection lazy on iteration
    first = failure() if lazy else error
    client = Client([first, _reply('{"tool":"read","args":{"path":"README.md"}}')])
    runtime = _runtime(client)
    response = runtime.generate([], [READ])
    assert response.tool_calls[0].arguments == {"path": "README.md"}
    assert len(client.calls) == 2
    assert client.calls[0]["tools"] == [READ]
    assert "tools" not in client.calls[1] and "stream" not in client.calls[1]
    assert runtime.supports_native_tools is False


def test_explicit_capability_metadata_skips_native_tools_and_is_cached():
    client = Client([_reply('{"tool":"read","args":{"path":"README.md"}}'),
                     _reply("Finished the read-only check.")], capabilities=["completion", "vision"])
    runtime = _runtime(client)
    assert runtime.generate([], [READ]).tool_calls[0].name == "read"
    assert runtime.generate([], [READ]).content == "Finished the read-only check."
    assert len(client.calls) == 2 and all("tools" not in call for call in client.calls)
    assert client.shows == 1


def test_missing_or_broken_capability_metadata_keeps_native_probe():
    class BrokenShow(Client):
        def show(self, model: str):
            raise RuntimeError("older server has no show metadata")
    client = BrokenShow([iter([_reply("Native result")])])
    assert _runtime(client).generate([], [READ]).content == "Native result"
    assert client.calls[0]["tools"] == [READ]


def test_compatibility_read_only_delegate_executes_valid_read(tmp_path: Path):
    (tmp_path / "README.md").write_text("# Requirements\n")
    client = Client([
        ResponseError(UNSUPPORTED, 400),
        _reply('{"tool":"read","args":{"path":"README.md"}}'),
        _reply("Requirements: inspect README; no writes needed."),
    ])
    delegate = ReadOnlyDelegate(
        _runtime(client), tmp_path, tmp_path / ".logs", SharedEvidenceCache(), max_turns=3
    )
    result = delegate.run("Read README.md")
    assert result["tool_calls"] == 1
    assert result["sources"][0]["ref"] == "README.md"
    assert "Requirements" in result["memo"]
    assert all("tools" not in call for call in client.calls[1:])
    assert all(message["role"] != "tool" and "tool_calls" not in message
               for message in client.calls[-1]["messages"])


def test_prose_wrapped_tool_json_cannot_be_recovered_by_harness():
    client = Client([_reply('I will call this now: `{"tool":"write","args":{"path":"x"}}`')],
                    capabilities=["completion"])
    with pytest.raises(ToolCompatibilityError, match="JSON tool response"):
        _runtime(client).generate([], [WRITE])
    final = _runtime(Client([_reply("Task is complete.")], capabilities=["completion"]))
    response = final.generate([], [WRITE])
    CodingHarness._compatibility_tool_call(response)
    assert response.content == "Task is complete." and not response.tool_calls


@pytest.mark.parametrize("bad", [
    '{"tool":"write","args":{"path":"owned.txt","content":"bad"}}',
    '{"tool":"read","args":{"path":23}}',
    '{"tool":"read","args":{}}',
    '{"tool":"read","args":',
    '{"tool":"unknown","args":{}}',
])
def test_unauthorized_or_malformed_json_is_not_executed(tmp_path: Path, bad: str):
    client = Client([_reply(bad)], capabilities=["completion"])
    delegate = ReadOnlyDelegate(
        _runtime(client), tmp_path, tmp_path / ".logs", SharedEvidenceCache(), max_turns=1
    )
    with pytest.raises(ToolCompatibilityError, match="JSON tool response"):
        delegate.run("Read only")
    assert not (tmp_path / "owned.txt").exists()


@pytest.mark.parametrize("partial_chunk", [
    _reply("Partial content"),
    {"message": {"tool_calls": [{"function": {
        "name": "read", "arguments": {"path": "README.md"}}}]}},
])
def test_partial_stream_rejection_never_replays(partial_chunk: dict):
    def partial():
        yield partial_chunk
        raise ResponseError(UNSUPPORTED, 400)
    client = Client([partial(), _reply('{"tool":"read","args":{"path":"README.md"}}')])
    with pytest.raises(ToolCompatibilityError, match="partial"):
        _runtime(client).generate([], [READ])
    assert len(client.calls) == 1


@pytest.mark.parametrize("error", [
    ResponseError("unauthorized", 401),
    ResponseError("rate limit", 429),
    ResponseError("context length exceeded", 400),
    TimeoutError("network timeout"),
])
def test_unrelated_errors_are_not_classified_as_unsupported(error: Exception):
    client = Client([error, _reply("should not run")])
    with pytest.raises(type(error)):
        _runtime(client).generate([], [READ])
    assert len(client.calls) == 1


def test_lazy_unrelated_http_failure_is_not_swallowed():
    def failure():
        raise ResponseError("context length exceeded", 400)
        yield
    client = Client([failure(), _reply("should not run")])
    with pytest.raises(ResponseError, match="context length"):
        _runtime(client).generate([], [READ])
    assert len(client.calls) == 1


def test_research_stage_invalid_compatibility_evidence_needs_attention(tmp_path: Path):
    client = Client([ResponseError(UNSUPPORTED, 400), _reply('{"tool":"read","args":')])
    runtime = _runtime(client)
    scheduler = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot(free_percent=50))
    run_dir = tmp_path / ".run"
    harness = CodingHarness(runtime=scheduler, workspace=tmp_path, run_dir=run_dir,
                            task="Read README.md", model_retries=0, retry_backoff_seconds=0)
    state = {"verification": {"verdict": "MISSING", "checks": []}}
    coordinator = AdaptiveOrchestra(
        harness, scheduler, scheduler, task="Read README.md", workspace=tmp_path,
        run_dir=run_dir, state=state, network_enabled=False, privacy_profile="guarded",
        progress=lambda *_: None, persist=lambda: None,
    )
    result = coordinator.run()
    assert result.status == "needs_attention"
    assert "JSON tool response" in result.final
    assert state["orchestra"]["research"] == "needs_attention"


def test_coding_stage_can_write_via_compatibility_and_finish(tmp_path: Path):
    client = Client([
        _reply(json.dumps({"tool": "write", "args": {"path": "note.md", "content": "Done.\n"}})),
        _reply("Created note.md."),
    ], capabilities=["completion"])
    harness = CodingHarness(
        runtime=_runtime(client), workspace=tmp_path, run_dir=tmp_path / ".run",
        task="Create note.md", model_retries=0, retry_backoff_seconds=0,
    )
    result = harness.run()
    assert result.status == "completed", result.final
    assert (tmp_path / "note.md").read_text() == "Done.\n"
    assert all("tools" not in call for call in client.calls)


def test_coding_invalid_compatibility_preserves_completed_write(tmp_path: Path):
    client = Client([
        _reply('{"tool":"write","args":{"path":"note.md","content":"Kept.\\n"}}'),
        _reply('{"tool":"write","args":'),
    ], capabilities=["completion"])
    harness = CodingHarness(
        runtime=_runtime(client), workspace=tmp_path, run_dir=tmp_path / ".run",
        task="Create note.md", model_retries=2, retry_backoff_seconds=0,
    )
    result = harness.run()
    assert result.status == "needs_attention"
    assert "JSON tool response" in result.final
    assert (tmp_path / "note.md").read_text() == "Kept.\n"
    assert len(client.calls) == 2  # No unrelated model retry or repeated write.
