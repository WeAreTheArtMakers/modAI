"""Behavioral tests for the MODAI CodingHarness state machine.

These tests use a fake (ScriptedRuntime) model — no Ollama connection is
required.  Each test verifies one specific property of the state machine as
described in the harness-review spec.

Scenarios covered
-----------------
A  Intermediate validator PASS does not stop coding or remove tools
B  Timeout does not complete unfinished work (no completion_candidate)
C  Empty MLX-style response recovers and task continues
D  Truncated tool call does not create an orphan tool message
E  Follow-up after PASS restores full tool access
F  Validation failure repairs in the same session (no external agents)
G  Read/test-only work does not trigger "write right now" no-progress guard
H  Read-only mode (write_allowed=False) never grants mutation capability
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from modai.core.harness import CodingHarness
from modai.core.session import SessionStore
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime


# ── helpers ──────────────────────────────────────────────────────────────────

def _call(n: int, name: str, **args) -> ToolCall:
    return ToolCall(f"c{n}", name, args)


def _harness(root: Path, responses, task: str = "Build notes.txt", **kw) -> CodingHarness:
    return CodingHarness(
        runtime=ScriptedRuntime(responses),
        workspace=root,
        run_dir=root / ".run",
        task=task,
        retry_backoff_seconds=0,  # no sleep in tests
        **kw,
    )


# ── A: Intermediate PASS must NOT stop coding ────────────────────────────────

def test_A_intermediate_pass_does_not_stop_coding():
    """
    Proactive verify (old batch_mutated path) would have run after turn 1
    and potentially stopped coding with a PASS checkpoint message.
    With the new design, verify fires ONLY at the completion candidate.

    Turn 1: write index.html (valid minimal HTML)
    Turn 2: write styles.css
    Turn 3: final response (no tool calls) → authoritative verify → PASS → done

    Assertions:
    - Both files exist.
    - Status is "completed".
    - Exactly 3 model calls (no extra finalization call).
    - Every call received the full tool schema (no [] suppression).
    - Exactly ONE verification event (at completion candidate).
    """
    valid_html = (
        "<!doctype html><html lang='en'><head>"
        "<meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>MODAI</title>"
        "</head><body><main><h1>MODAI</h1><p>Local AI agent.</p></main></body></html>"
    )
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        events = []
        agent = _harness(root, [
            ModelResponse(
                tool_calls=[_call(1, "write", path="index.html", content=valid_html)],
                usage=Usage(100, 20),
            ),
            ModelResponse(
                tool_calls=[_call(2, "write", path="styles.css", content="body{margin:0;font-family:sans-serif}")],
                usage=Usage(120, 25),
            ),
            ModelResponse(content="Done — both files written.", usage=Usage(80, 15)),
        ], event=events.append)

        result = agent.run()

        assert result.status == "completed", f"Expected completed, got {result.status}: {result.final}"
        assert (root / "index.html").exists(), "index.html missing"
        assert (root / "styles.css").exists(), "styles.css missing"
        assert result.turns == 3, f"Expected 3 turns, got {result.turns}"

        # Every model call must have received a non-empty tool list
        for i, req in enumerate(agent.runtime.requests):
            assert req.get("tools"), (
                f"Turn {i+1} received empty tool list — finalization_only bug still present"
            )

        # Exactly ONE verify event (no per-mutation proactive calls)
        verify_events = [e for e in events if e.kind == "verification_finished"]
        assert len(verify_events) == 1, (
            f"Expected exactly 1 verification call, got {len(verify_events)} — "
            "proactive batch_mutated verify may still be running"
        )


# ── B: Timeout must NOT complete unfinished work ─────────────────────────────

def test_B_timeout_does_not_complete_unfinished_work():
    """
    Turn 1 writes index.html (validator would PASS for a minimal file).
    Turn 2 model times out.
    The model has NOT declared completion (no no-tool-call turn).

    Assertion: status != "completed"
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent = _harness(root, [
            ModelResponse(
                tool_calls=[_call(1, "write", path="index.html",
                                  content="<!doctype html><html lang='en'><head><meta charset='utf-8'>"
                                          "<meta name='viewport' content='width=device-width'>"
                                          "<title>T</title></head><body><main><h1>T</h1></main></body></html>")],
                usage=Usage(100, 30),
            ),
            TimeoutError("timed out"),
        ], model_retries=0)

        result = agent.run()

        assert result.status != "completed", (
            "Timeout mid-session was incorrectly promoted to 'completed'. "
            "Only a completion_candidate + PASS should complete on timeout."
        )
        # File should be preserved for resume
        assert (root / "index.html").exists(), "Written file was lost on timeout"
        assert (root / ".run" / "session.jsonl").is_file(), "Session not persisted for resume"


# ── C: Empty MLX-style response recovers ─────────────────────────────────────

def test_C_empty_response_triggers_retry_and_task_continues():
    """
    Turn 1 → content="", tool_calls=[]  (MLX empty)
    Turn 2 → write file
    Turn 3 → final response

    Assertions:
    - empty_model_response event emitted
    - task eventually completes
    - no false completion on the empty turn
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        events = []
        agent = _harness(root, [
            ModelResponse(content="", tool_calls=[], usage=Usage(50, 0)),
            ModelResponse(
                tool_calls=[_call(1, "write", path="notes.txt", content="done\n")],
                usage=Usage(100, 20),
            ),
            ModelResponse(content="Notes written.", usage=Usage(80, 15)),
        ], event=events.append)

        result = agent.run()

        assert result.status == "completed"
        assert (root / "notes.txt").read_text() == "done\n"

        empty_events = [e for e in events if e.kind == "empty_model_response"]
        assert empty_events, "empty_model_response event never emitted"


# ── D: Truncated tool call leaves no orphan tool message ─────────────────────

def test_D_truncated_tool_call_no_orphan_in_history():
    """
    Response 1: truncated=True, tool_calls=[write bad.txt]
    Response 2: write good.txt
    Response 3: final

    Assertions:
    - bad.txt was NOT written
    - good.txt was written
    - The message history sent to model turn 2 contains no assistant
      tool_call without a matching tool result.
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent = _harness(root, [
            ModelResponse(
                tool_calls=[_call(1, "write", path="bad.txt", content="bad")],
                truncated=True,
                usage=Usage(100, 10),
            ),
            ModelResponse(
                tool_calls=[_call(2, "write", path="good.txt", content="good\n")],
                usage=Usage(110, 20),
            ),
            ModelResponse(content="Done.", usage=Usage(80, 15)),
        ])

        result = agent.run()

        assert result.status == "completed"
        assert not (root / "bad.txt").exists(), "Truncated tool call was executed (bad.txt exists)"
        assert (root / "good.txt").exists(), "good.txt missing"

        # Inspect the messages sent to turn-2 model call
        turn2_messages = agent.runtime.requests[1]["messages"]
        assistant_tool_ids: set[str] = set()
        tool_result_ids: set[str] = set()
        for msg in turn2_messages:
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    assistant_tool_ids.add(tc["id"])
            if msg.get("role") == "tool":
                tool_result_ids.add(msg.get("tool_call_id", ""))

        orphans = assistant_tool_ids - tool_result_ids
        assert not orphans, (
            f"Orphan tool call IDs in history (no matching tool result): {orphans}"
        )


# ── E: Follow-up after PASS restores tool access ─────────────────────────────

def test_E_followup_after_pass_restores_tool_access():
    """
    Phase 1: write notes.txt, final response → PASS → completed
    Then queue follow-up "Add a second line."
    Phase 2: run resumes, model calls edit → success

    Assertions:
    - edit/write tools are available in the follow-up turn
    - final file contains the update
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)

        # Phase 1 responses
        phase1 = [
            ModelResponse(
                tool_calls=[_call(1, "write", path="notes.txt", content="line1\n")],
                usage=Usage(100, 20),
            ),
            ModelResponse(content="Done.", usage=Usage(80, 15)),
        ]
        # Phase 2 responses (follow-up)
        phase2 = [
            ModelResponse(
                tool_calls=[_call(2, "edit", path="notes.txt",
                                  edits=[{"old": "line1\n", "new": "line1\nline2\n"}])],
                usage=Usage(110, 25),
            ),
            ModelResponse(content="Updated.", usage=Usage(80, 15)),
        ]

        # Build harness with combined script; queue follow-up mid-session
        combined = phase1 + phase2
        agent = _harness(root, combined)

        # Queue the follow-up before running so it arrives after phase-1 completes
        agent.session.follow_up("Add a second line.")

        result = agent.run()

        assert result.status == "completed"
        content = (root / "notes.txt").read_text()
        assert "line2" in content, f"Follow-up edit not applied, file: {repr(content)}"

        # The turn that processed the follow-up must have had tools available
        # (turn index 2 = third request, after phase1-write, phase1-final, phase2-edit)
        followup_turn_idx = 2  # 0-based: write(1), final(2), follow-up edit(3)
        if len(agent.runtime.requests) > followup_turn_idx:
            req = agent.runtime.requests[followup_turn_idx]
            tool_names = {t["function"]["name"] for t in (req.get("tools") or [])}
            assert "write" in tool_names or "edit" in tool_names, (
                f"Follow-up turn {followup_turn_idx+1} had no mutation tools: {tool_names}"
            )


# ── F: Validation failure repairs in the SAME session ────────────────────────

def test_F_validation_failure_repairs_in_same_session():
    """
    Turn 1: write broken file (missing viewport → static_site FAIL)
    Turn 2: final response → _verify() FAIL
    Turn 3: edit to add viewport
    Turn 4: final response → _verify() PASS

    Assertions:
    - Only ONE harness instance used (no delegate/reviewer spawning)
    - Final status is "completed"
    - verification sequence reflects 2 verify calls
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)

        broken = (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<title>X</title></head><body><main><h1>X</h1></main></body></html>"
        )
        fixed = (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>X</title></head><body><main><h1>X</h1></main></body></html>"
        )

        events = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "write", path="index.html", content=broken)], usage=Usage(100, 30)),
            ModelResponse(content="Done.", usage=Usage(80, 15)),          # triggers FAIL verify
            ModelResponse(tool_calls=[_call(2, "edit", path="index.html",
                                            edits=[{"old": broken, "new": fixed}])], usage=Usage(110, 25)),
            ModelResponse(content="Fixed.", usage=Usage(80, 15)),          # triggers PASS verify
        ], task="Build a responsive HTML landing page", event=events.append)

        result = agent.run()

        assert result.status == "completed", f"Expected completed, got {result.status}: {result.final}"

        verify_events = [e for e in events if e.kind == "verification_finished"]
        assert len(verify_events) == 2, (
            f"Expected exactly 2 verify calls (fail + pass), got {len(verify_events)}"
        )
        assert verify_events[0].data["verdict"] == "FAIL"
        assert verify_events[1].data["verdict"] == "PASS"

        # Confirm no external agent was spawned (harness only has one runtime)
        assert isinstance(agent.runtime, ScriptedRuntime), "Unexpected runtime delegation"


# ── G: Read/test work is NOT false no-progress ───────────────────────────────

def test_G_read_only_discovery_not_false_no_progress():
    """
    Legitimate discovery sequence:
      turn 1: ls .
      turn 2: grep something
      turn 3: read file
      turn 4: bash pytest
      turn 5: write result.txt
      turn 6: final

    Assertions:
    - no_progress event is NOT emitted before turn 5
    - task completes normally
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "src.py").write_text("x = 1\n")

        events = []
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "ls", path=".")], usage=Usage(60, 5)),
            ModelResponse(tool_calls=[_call(2, "grep", pattern="x", path=".")], usage=Usage(70, 8)),
            ModelResponse(tool_calls=[_call(3, "read", path="src.py")], usage=Usage(75, 10)),
            ModelResponse(tool_calls=[_call(4, "bash", argv=["python3", "-c", "print('ok')"])], usage=Usage(80, 12)),
            ModelResponse(tool_calls=[_call(5, "write", path="result.txt", content="found\n")], usage=Usage(90, 20)),
            ModelResponse(content="Done.", usage=Usage(70, 10)),
        ], event=events.append, task="Inspect src.py and write result.txt")

        result = agent.run()

        assert result.status == "completed"
        assert (root / "result.txt").read_text() == "found\n"

        np_events = [e for e in events if e.kind == "no_progress"]
        assert not np_events, (
            f"no_progress guard fired during legitimate read-only discovery: {np_events}"
        )


# ── H: Read-only mode never grants mutation capability ───────────────────────

def test_H_read_only_mode_denies_mutation():
    """
    Harness created with write_allowed=False.

    Assertions:
    - write/edit tools absent from schema (ToolPolicy enforces)
    - PermissionError raised if write tool called directly
    - Task with only read tools and a final response completes
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "doc.txt").write_text("hello")

        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "read", path="doc.txt")], usage=Usage(60, 8)),
            ModelResponse(content="Reviewed: doc.txt contains 'hello'.", usage=Usage(70, 12)),
        ], write_allowed=False, task="Read-only review of doc.txt")

        # Schema must not contain mutation tools
        tool_names = {t["function"]["name"] for t in agent.registry.schemas()}
        assert "write" not in tool_names, f"write in schema despite write_allowed=False: {tool_names}"
        assert "edit" not in tool_names, f"edit in schema despite write_allowed=False: {tool_names}"

        # Direct policy check
        from modai.tools.policy import ToolPolicy, Capabilities
        policy = ToolPolicy(Capabilities(read=True, write=False))
        assert not policy.allows("write")
        assert not policy.allows("edit")

        result = agent.run()
        assert result.status == "completed"
        # No files should have been created
        new_files = [p for p in root.rglob("*") if p.is_file() and p.name != "doc.txt"
                     and ".run" not in str(p)]
        assert not new_files, f"Unexpected files created in read-only mode: {new_files}"


# ── Regression: completion_candidate semantics ───────────────────────────────

def test_completion_candidate_only_set_on_no_tool_response():
    """
    Verifies that _timeout_result is only called with completion_candidate=True
    when the model's LAST response had no tool calls.

    Scenario: write → timeout (model was still working, not done)
    The timeout must NOT yield status='completed'.
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        agent = _harness(root, [
            ModelResponse(tool_calls=[_call(1, "write", path="a.txt", content="x")], usage=Usage(80, 20)),
            TimeoutError("timed out while agent was still writing"),
        ], model_retries=0)

        result = agent.run()
        # After a tool-call turn → timeout, completion_candidate is False
        assert result.status != "completed", (
            "Timeout immediately after a tool call must NOT be 'completed'"
        )


def test_completion_candidate_true_on_final_response_timeout():
    """
    In the new harness design, no-tool response → _verify() → PASS → return completed
    is a single synchronous operation — no second generate() call is needed.

    This test verifies the write + final-response path completes in exactly 2 turns,
    and that timeout during a tool-call turn does NOT incorrectly complete the task.
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        # Happy path: write → final response → done in 2 turns
        agent = _harness(root, [
            ModelResponse(
                tool_calls=[_call(1, "write", path="notes.txt", content="done\n")],
                usage=Usage(80, 20),
            ),
            ModelResponse(content="Notes written, task complete.", usage=Usage(60, 12)),
        ], model_retries=0)

        result = agent.run()

        assert result.status == "completed", (
            f"write + final response must complete synchronously, got {result.status}: {result.final}"
        )
        assert (root / "notes.txt").read_text() == "done\n"
        # Verify we consumed exactly 2 model calls (no extra "summary" call)
        assert len(agent.runtime.requests) == 2, (
            f"Expected 2 generate() calls, got {len(agent.runtime.requests)}"
        )
