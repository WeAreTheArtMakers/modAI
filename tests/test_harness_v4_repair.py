"""V4 targeted-repair regression tests.

Locks in the working v4 baseline (checkpoint c00c0b4):
  valid landing page
    -> browser FAIL (table.tools-table overflow at 390px)
    -> repair context resolves styles.css + line range + CSS block
    -> repair-mode tools: read/grep/edit only (no write, no bash)
    -> ONE edit
    -> immediate verify
    -> browser PASS -> completed (no extra final-summary model call)

Plus:
  - structural repair keeps write when a required file is missing
  - _is_structural_failure unit semantics
  - _resolve_css_selector priority + no HTML-class false positive
  - repair turn budget (max 3 repair turns)
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.quality.project import CheckResult, VerificationReport


def _call(n: int, name: str, **args) -> ToolCall:
    return ToolCall(f"c{n}", name, args)


def _harness(root: Path, responses, task: str, **kw) -> CodingHarness:
    return CodingHarness(
        runtime=ScriptedRuntime(responses),
        workspace=root,
        run_dir=root / ".run",
        task=task,
        retry_backoff_seconds=0,
        **kw,
    )


GOOD_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width,initial-scale=1'>"
    "<title>MODAI</title><link rel='stylesheet' href='styles.css'></head>"
    "<body><main><h1>MODAI</h1><p>Local coding harness.</p>"
    '<table class="tools-table"><tr><td>tool A</td><td>tool B</td></tr></table>'
    "</main><script src='app.js'></script></body></html>"
)

CSS_BAD = (
    "*{box-sizing:border-box}body{margin:0;max-width:100%;font-family:sans-serif}"
    "main{padding:2rem}\n"
    ".tools-table {\n"
    "    width: 408px;\n"
    "}"
)

CSS_GOOD = (
    "*{box-sizing:border-box}body{margin:0;max-width:100%;font-family:sans-serif}"
    "main{padding:2rem}\n"
    ".tools-table {\n"
    "    width: 100%;\n"
    "    max-width: 100%;\n"
    "    overflow-x: auto;\n"
    "}"
)

GOOD_JS = "document.documentElement.dataset.ready='true';\n"


def test_v4_targeted_css_overflow_immediate_verify():
    """Core V4 flow: ONE targeted edit -> immediate reverify -> DONE.

    Scripted model:
      1-3. write index.html / styles.css (408px overflow) / app.js
      4. final -> verifier FAIL (browser overflow table.tools-table)
      5. edit styles.css (408px -> 100%/max-width/overflow-x)
      -- harness must immediately verify and return completed --
      6. (must NOT exist) another final summary call
    """
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        events: list = []
        agent = _harness(
            root,
            [
                ModelResponse(
                    tool_calls=[_call(1, "write", path="index.html", content=GOOD_HTML)],
                    usage=Usage(100, 20),
                ),
                ModelResponse(
                    tool_calls=[_call(2, "write", path="styles.css", content=CSS_BAD)],
                    usage=Usage(100, 20),
                ),
                ModelResponse(
                    tool_calls=[_call(3, "write", path="app.js", content=GOOD_JS)],
                    usage=Usage(100, 20),
                ),
                ModelResponse(content="Done.", usage=Usage(80, 15)),
                ModelResponse(
                    tool_calls=[
                        _call(
                            4,
                            "edit",
                            path="styles.css",
                            edits=[
                                {
                                    "old": "    width: 408px;",
                                    "new": "    width: 100%;\n    max-width: 100%;\n    overflow-x: auto;",
                                }
                            ],
                        )
                    ],
                    usage=Usage(110, 25),
                ),
            ],
            task="Build a responsive landing page",
            event=events.append,
        )

        result = agent.run()

        # Terminal state
        assert result.status == "completed", f"got {result.status}: {result.final}"
        assert result.verification["verdict"] == "PASS"
        # Initial FAIL + repair PASS, nothing else
        assert result.verification.get("sequence") == 2, result.verification

        # No extra final-summary model call after deterministic repair
        assert len(agent.runtime.requests) == 5, (
            f"expected 5 model calls (3 writes + final + 1 repair edit), "
            f"got {len(agent.runtime.requests)}"
        )
        assert result.metrics["model_calls"] == 5

        # Repair turn (5th request, index 4) is restricted: read/grep/edit only
        repair_tools = {
            t["function"]["name"] for t in agent.runtime.requests[4].get("tools", [])
        }
        assert repair_tools == {"read", "grep", "edit"}, (
            f"targeted repair must be read/grep/edit only, got {repair_tools}"
        )
        assert "write" not in repair_tools, "write must be unavailable in targeted repair"
        assert "bash" not in repair_tools, "bash must be unavailable in targeted repair"

        # Repair context resolved the CSS source
        repair_msgs = agent.runtime.requests[4]["messages"]
        last_user = [m for m in repair_msgs if m.get("role") == "user"][-1]
        assert "styles.css" in last_user["content"], last_user["content"][:1000]
        assert ".tools-table" in last_user["content"] or "tools-table" in last_user["content"]

        # Verification events: FAIL then PASS, plus a repair_revalidation PASS
        verify = [e for e in events if e.kind == "verification_finished"]
        assert len(verify) == 2, f"expected 2 verifications, got {len(verify)}"
        assert verify[0].data["verdict"] == "FAIL"
        assert verify[1].data["verdict"] == "PASS"
        reval = [e for e in events if e.kind == "repair_revalidation"]
        assert reval and reval[-1].data.get("verdict") == "PASS"

        # Fixed file on disk
        assert "width: 408px" not in (root / "styles.css").read_text()


def test_v4_structural_missing_file_allows_write():
    """Missing required file -> structural repair keeps write available."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        events: list = []
        agent = _harness(
            root,
            [
                ModelResponse(
                    tool_calls=[_call(1, "write", path="report.md", content="# hi\n")],
                    usage=Usage(50, 10),
                ),
                ModelResponse(content="done", usage=Usage(50, 10)),
                ModelResponse(
                    tool_calls=[_call(2, "write", path="data.json", content='{"a":1}')],
                    usage=Usage(50, 10),
                ),
            ],
            task="Create report.md and data.json",
            event=events.append,
        )
        result = agent.run()

        assert result.status == "completed", f"got {result.status}: {result.final}"
        assert result.verification.get("sequence") == 2
        # Immediate verify: 3 model calls, no 4th summary call
        assert len(agent.runtime.requests) == 3

        repair_tools = {
            t["function"]["name"] for t in agent.runtime.requests[2].get("tools", [])
        }
        assert "write" in repair_tools, (
            f"structural repair must keep write, got {repair_tools}"
        )
        started = [e for e in events if e.kind == "repair_started"]
        assert started and started[0].data.get("structural") is True


def test_v4_is_structural_failure_unit():
    missing = VerificationReport(
        "FAIL",
        [CheckResult("artifact_contract", "FAIL",
                     ["required file is missing or empty: styles.css"], {})],
        1, [],
    )
    assert CodingHarness._is_structural_failure(missing) is True

    targeted = VerificationReport(
        "FAIL",
        [CheckResult("browser_quality", "FAIL",
                     ["mobile: horizontal overflow 440>390 — likely offender: "
                      "table.tools-table (element width 408px, overflow 50px)"], {})],
        1, [],
    )
    assert CodingHarness._is_structural_failure(targeted) is False


def test_v4_resolve_css_selector_prefers_css_and_ignores_html_class():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "index.html").write_text(
            "<!doctype html><html><body><table class=\"tools-table\"></table></body></html>"
        )
        (root / "styles.css").write_text(
            "body{margin:0}\n.tools-table {\n    width: 408px;\n}\n"
        )
        agent = _harness(root, [], task="probe")
        hit = agent._resolve_css_selector("table.tools-table")
        assert hit is not None, "expected CSS source resolution"
        assert hit["file"] == "styles.css"
        assert "width: 408px" in hit["snippet"]

        # HTML class attribute alone is NOT a CSS definition
        (root / "styles.css").unlink()
        agent2 = _harness(root, [], task="probe")
        assert agent2._resolve_css_selector("table.tools-table") is None


def test_v4_build_repair_context_includes_source_and_measurements():
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "styles.css").write_text(
            "body{margin:0}\n.tools-table {\n    width: 408px;\n}\n"
        )
        agent = _harness(root, [], task="Build a responsive landing page")
        report = VerificationReport(
            "FAIL",
            [CheckResult(
                "browser_quality", "FAIL",
                ["mobile (390x844): horizontal overflow 440>390 — likely offender: "
                 "table.tools-table (element width 408px, overflow 50px). "
                 "Fix: add max-width:100%; overflow-x:auto or clip with overflow:hidden."],
                {})],
            1, [],
        )
        import json as _json

        ctx_text = agent._build_repair_context(report)
        payload = _json.loads(ctx_text.split("\n\nMake the smallest")[0])
        assert payload["mode"] == "REPAIR"
        err = payload["failures"][0]["errors"][0]
        assert err["selector"] == "table.tools-table"
        assert err["source"]["file"] == "styles.css"
        assert err["measurements"]["element_width_px"] == 408
        assert err["measurements"]["viewport_width_px"] == 390


def test_v4_repair_turn_budget_limits_to_three():
    """Repair edits that never fix the failure stop after 3 repair turns."""
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        events: list = []
        agent = _harness(
            root,
            [
                ModelResponse(
                    tool_calls=[_call(1, "write", path="report.md", content="# hi\n")],
                    usage=Usage(50, 10),
                ),
                ModelResponse(content="done", usage=Usage(50, 10)),
                ModelResponse(
                    tool_calls=[_call(2, "edit", path="report.md",
                                      edits=[{"old": "# hi\n", "new": "# hi v2\n"}])],
                    usage=Usage(50, 10),
                ),
                ModelResponse(
                    tool_calls=[_call(3, "edit", path="report.md",
                                      edits=[{"old": "# hi v2\n", "new": "# hi v3\n"}])],
                    usage=Usage(50, 10),
                ),
                ModelResponse(
                    tool_calls=[_call(4, "edit", path="report.md",
                                      edits=[{"old": "# hi v3\n", "new": "# hi v4\n"}])],
                    usage=Usage(50, 10),
                ),
                ModelResponse(
                    tool_calls=[_call(5, "edit", path="report.md",
                                      edits=[{"old": "# hi v4\n", "new": "# hi v5\n"}])],
                    usage=Usage(50, 10),
                ),
            ],
            task="Create report.md and data.json",
            event=events.append,
            max_turns=20,
        )
        result = agent.run()
        assert result.status == "needs_attention"
        assert "3-turn limit" in result.final
        assert any(e.kind == "repair_turn_limit" for e in events)
