from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from config import Settings, load_settings
from contracts import evaluate_artifact_contract, infer_artifact_contract
from evidence_cache import EvidenceCache
from model_advisor import HardwareProfile, recommend_model, render_modelfile
from orchestrator import CloudBudgetPaused, Orchestrator, TerminalUI, build_parser, dashboard_loop, extract_json, extract_tool_requests, set_orchestration_value
from providers import CloudClient, contains_obvious_secret
from roles import ROLES
from runtime_context import set_internet_enabled, set_workspace
from tools.filesystem import list_files, make_directory, read_file, write_file
from tools.terminal import _arguments, _validate
from tools.web import fetch_url, search_web
from tools.web_assets import validate_web_assets
from tools.static_site import validate_static_site
from tools.browser_gate import validate_browser_quality
from tui import Dashboard, _safe_pasted_text, decode_key
from worktree_isolation import IsolatedWorktree


class ConfigTests(unittest.TestCase):
    def test_model_advisor_selects_9b_for_16gb_machine(self) -> None:
        hardware = HardwareProfile("Darwin", "arm64", "Apple M1 Pro", 16.0, 10)
        selected = recommend_model(hardware)
        self.assertEqual(selected.name, "qwen3.5:9b")
        self.assertLess(selected.download_gb, hardware.memory_gb / 2)

    def test_model_advisor_renders_selected_base_without_changing_template(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            template = root / "Modelfile"
            output = root / "generated.Modelfile"
            template.write_text("FROM old:model\nPARAMETER num_ctx 8192\n", encoding="utf-8")
            render_modelfile(template, output, "qwen3.5:9b")
            self.assertEqual(template.read_text(), "FROM old:model\nPARAMETER num_ctx 8192\n")
            self.assertTrue(output.read_text().startswith("FROM qwen3.5:9b\n"))

    def test_orchestration_limits_are_available_on_command_line(self) -> None:
        args = build_parser().parse_args([
            "--max-total-tokens", "1500000", "--debate-rounds", "4",
            "--repair-rounds", "6", "--max-tool-rounds", "12", "--agent-retries", "3",
        ])
        self.assertEqual(args.max_total_tokens, 1_500_000)
        self.assertEqual(args.debate_rounds, 4)
        self.assertEqual(args.repair_rounds, 6)
        self.assertEqual(args.max_tool_rounds, 12)
        self.assertEqual(args.agent_retries, 3)

    def test_adaptive_parallel_cli_settings(self) -> None:
        args = build_parser().parse_args(["--execution-mode", "parallel", "--max-parallel-agents", "3"])
        self.assertEqual(args.execution_mode, "parallel")
        self.assertEqual(args.max_parallel_agents, 3)

    def test_file_and_environment_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"model": "file-model", "context_size": 4096}), encoding="utf-8")
            with patch.dict(os.environ, {"MOD_AGENT_MODEL": "env-model"}, clear=False):
                settings = load_settings(path)
        self.assertEqual(settings.model, "env-model")
        self.assertEqual(settings.context_size, 4096)

    def test_unknown_setting_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text('{"unknown": true}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_settings(path)

    def test_legacy_config_aliases_migrate_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(json.dumps({"cloud_token_budget": 2000000, "num_ctx": 16384,
                                        "mode": "solo", "local_token_limit": None}), encoding="utf-8")
            settings = load_settings(path)
        self.assertEqual(settings.cloud_token_budget, 2_000_000)
        self.assertEqual(settings.context_size, 16384)
        self.assertEqual(settings.harness_mode, "solo")

    def test_boolean_environment_setting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.json"
            with patch.dict(os.environ, {"MOD_AGENT_THINK": "true"}, clear=False):
                settings = load_settings(path)
        self.assertTrue(settings.think)

    def test_remote_model_host_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            Settings(host="https://remote.example").validate()

    def test_language_is_validated(self) -> None:
        Settings(language="en").validate()
        with self.assertRaises(ValueError):
            Settings(language="de").validate()

    def test_custom_orchestration_limits(self) -> None:
        agent = Orchestrator(Settings(), client=object())
        set_orchestration_value(agent, "debate_rounds", "12")
        set_orchestration_value(agent, "max_agents", "120")
        set_orchestration_value(agent, "num_ctx", "16384")
        set_orchestration_value(agent, "cloud_token_budget", "2000000")
        self.assertEqual(agent.settings.debate_rounds, 12)
        self.assertEqual(agent.settings.max_agents, 120)
        self.assertEqual(agent.settings.context_size, 16384)
        self.assertEqual(agent.settings.cloud_token_budget, 2_000_000)
        with self.assertRaises(ValueError):
            set_orchestration_value(agent, "repair_rounds", "99")


class ParsingTests(unittest.TestCase):
    def test_extracts_fenced_json(self) -> None:
        self.assertEqual(extract_json('text```json\n{"ok": true}\n```'), {"ok": True})

    def test_extracts_multiple_tool_objects_from_noisy_output(self) -> None:
        text = '{"tool":"file_exists","args":{"path":"index.html"}}\n</tool_call>\n{"tool":"make_directory","args":{"path":"assets"}}'
        self.assertEqual(extract_tool_requests(text), [
            ("file_exists", {"path": "index.html"}),
            ("make_directory", {"path": "assets"}),
        ])

    def test_obvious_cloud_secrets_are_detected(self) -> None:
        self.assertTrue(contains_obvious_secret("API_KEY=super-secret-value"))
        self.assertFalse(contains_obvious_secret("public market research about coffee"))

    def test_cloud_usage_is_normalized(self) -> None:
        response = CloudClient._normalized("ok", 12, 7)
        self.assertEqual(response["message"]["content"], "ok")
        self.assertEqual(response["prompt_eval_count"], 12)

    def test_cloud_provider_responses_are_normalized_without_network(self) -> None:
        messages = [{"role": "system", "content": "safe"}, {"role": "user", "content": "public task"}]
        fixtures = {
            "openai": {"output_text": "openai ok", "usage": {"input_tokens": 4, "output_tokens": 2}},
            "anthropic": {"content": [{"type": "text", "text": "anthropic ok"}], "usage": {"input_tokens": 5, "output_tokens": 3}},
            "google": {"candidates": [{"content": {"parts": [{"text": "google ok"}]}}], "usageMetadata": {"promptTokenCount": 6, "candidatesTokenCount": 4}},
        }
        with patch("providers.api_key_for", return_value="test-key"):
            for provider, fixture in fixtures.items():
                client = CloudClient(provider, "test-model")
                with patch.object(client, "_request", return_value=fixture):
                    response = client.chat(messages=messages, options={"num_predict": 100})
                self.assertIn("ok", response["message"]["content"])
                self.assertGreater(response["prompt_eval_count"], 0)


class TerminalSafetyTests(unittest.TestCase):
    def test_shell_operators_are_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            _arguments(["ls", ";", "rm", "-rf", "."])

    def test_mutating_git_is_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            _validate(["git", "commit", "-am", "unsafe"])

    def test_path_escape_is_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            _validate(["cat", "../../etc/passwd"])


class FakeClient:
    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.responses = [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {"function": {"name": "list_files", "arguments": {"path": "."}}}
                    ],
                }
            },
            {"message": {"content": "İnceleme tamamlandı.", "tool_calls": []}},
        ]

    def chat(self, **kwargs):
        self.requests.append(kwargs)
        return self.responses.pop(0)


class ToolLoopTests(unittest.TestCase):
    def test_multiple_fallback_tool_objects_are_executed(self) -> None:
        class MultiToolClient:
            def __init__(self):
                self.responses = [
                    {"message": {"content": '{"tool":"make_directory","args":{"path":"assets/icons"}}\n</tool_call>\n{"tool":"file_exists","args":{"path":"assets/icons"}}'}},
                    {"message": {"content": "done"}},
                ]

            def chat(self, **_kwargs):
                return self.responses.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            set_workspace(directory)
            agent = Orchestrator(Settings(workspace=directory), client=MultiToolClient())
            result = agent.chat_agent("coder", "create assets")
            self.assertEqual(result, "done")
            self.assertTrue((Path(directory) / "assets/icons").is_dir())
            self.assertEqual([item["tool"] for item in agent.tool_trace], ["make_directory", "file_exists"])

    def test_token_usage_is_accumulated(self) -> None:
        class UsageClient:
            def chat(self, **_kwargs):
                return {"message": {"content": "ok"}, "prompt_eval_count": 31, "eval_count": 9}

        events = []
        agent = Orchestrator(Settings(), client=UsageClient(), event=lambda kind, message: events.append((kind, message)))
        agent.chat_agent("finalizer", "test")
        self.assertEqual(agent.usage["input_tokens"], 31)
        self.assertEqual(agent.usage["output_tokens"], 9)
        self.assertIn("activity_start", {kind for kind, _ in events})
        self.assertIn("activity_stop", {kind for kind, _ in events})

    def test_local_tokens_are_unlimited_even_above_cloud_budget(self) -> None:
        class ExpensiveClient:
            def chat(self, **_kwargs):
                return {"message": {"content": "ok"}, "prompt_eval_count": 900, "eval_count": 200}

        agent = Orchestrator(Settings(max_total_tokens=1000), client=ExpensiveClient())
        self.assertEqual(agent.chat_agent("finalizer", "test"), "ok")
        self.assertEqual(agent.usage["cloud_input_tokens"], 0)

    def test_cloud_budget_can_be_extended_without_stopping_agent(self) -> None:
        class ExpensiveClient:
            def chat(self, **_kwargs):
                return {"message": {"content": "cloud ok"}, "prompt_eval_count": 900, "eval_count": 200}

        extensions = []
        agent = Orchestrator(
            Settings(cloud_enabled=True, cloud_model="cloud", max_total_tokens=1000),
            client=object(), cloud_budget_handler=lambda used, budget: extensions.append((used, budget)) or 1_000_000,
        )
        agent.cloud_client = ExpensiveClient()
        self.assertEqual(agent.chat_agent("finalizer", "test", use_cloud=True), "cloud ok")
        self.assertEqual(extensions, [(1100, 1000)])
        self.assertEqual(agent.settings.cloud_token_budget, 1_001_000)

    def test_cloud_budget_without_user_extension_pauses(self) -> None:
        class ExpensiveClient:
            def chat(self, **_kwargs):
                return {"message": {"content": "cloud ok"}, "prompt_eval_count": 900, "eval_count": 200}

        agent = Orchestrator(
            Settings(cloud_enabled=True, cloud_model="cloud", max_total_tokens=1000), client=object(),
        )
        agent.cloud_client = ExpensiveClient()
        with self.assertRaises(CloudBudgetPaused):
            agent.chat_agent("finalizer", "test", use_cloud=True)

    def test_cloud_routing_requires_opt_in_public_web_task(self) -> None:
        settings = Settings(cloud_enabled=True, cloud_model="cloud-model")
        agent = Orchestrator(settings, client=object())
        public = {"role": "market_researcher", "task": "public coffee market", "deliverable": "report", "needs_web": True}
        secret = {**public, "task": "research API_KEY=super-secret-value"}
        self.assertTrue(agent._cloud_task_eligible({"cloud_allowed": True}, public))
        self.assertFalse(agent._cloud_task_eligible({"cloud_allowed": False}, public))
        self.assertFalse(agent._cloud_task_eligible({"cloud_allowed": True}, secret))

    def test_native_tool_call_is_executed_and_returned(self) -> None:
        fake = FakeClient()
        agent = Orchestrator(Settings(), client=fake)
        result = agent.chat_agent("architect", "Dosyaları incele")
        self.assertEqual(result, "İnceleme tamamlandı.")
        self.assertEqual(agent.tool_trace[0]["tool"], "list_files")
        second_messages = fake.requests[1]["messages"]
        self.assertEqual(second_messages[-1]["role"], "tool")

    def test_agent_is_reminded_to_collect_real_evidence(self) -> None:
        class ReluctantClient:
            def __init__(self) -> None:
                self.responses = [
                    {"message": {"content": "Dosya muhtemelen var.", "tool_calls": []}},
                    {"message": {"content": "", "tool_calls": [
                        {"function": {"name": "file_exists", "arguments": {"path": "README.txt"}}}
                    ]}},
                    {"message": {"content": "Dosya doğrulandı.", "tool_calls": []}},
                ]

            def chat(self, **_kwargs):
                return self.responses.pop(0)

        agent = Orchestrator(Settings(), client=ReluctantClient())
        result = agent.chat_agent("researcher", "README.txt var mı?")
        self.assertEqual(result, "Dosya doğrulandı.")
        self.assertEqual(agent.tool_trace[0]["tool"], "file_exists")

    def test_read_only_mode_removes_write_tools(self) -> None:
        agent = Orchestrator(Settings(), client=object())
        agent.write_allowed = False
        self.assertNotIn("write_file", agent._allowed_tools("coder"))
        self.assertNotIn("replace_in_file", agent._allowed_tools("integrator"))

    def test_negative_instruction_is_inferred_as_read_only(self) -> None:
        self.assertFalse(Orchestrator._infer_write_allowed("incele ama dosya değiştirme"))
        self.assertTrue(Orchestrator._infer_write_allowed("dosyayı geliştir ve test et"))

    def test_final_prompt_uses_machine_write_facts(self) -> None:
        agent = Orchestrator(Settings(), client=object())
        prompt = agent._final_prompt({
            "task": "incele", "plan": {}, "outputs": [], "write_allowed": False,
        })
        self.assertIn("Çalışma modu: salt okunur", prompt)
        self.assertIn("Başarılı dosya yazmaları: YOK", prompt)

    def test_machine_static_site_failure_overrides_model_gate_passes(self) -> None:
        state = {
            "outputs": [
                {"role": "reviewer", "output": "VERDICT: PASS"},
                {"role": "tester", "output": "VERDICT: PASS"},
                {"role": "security_reviewer", "output": "VERDICT: PASS"},
            ],
            "tool_trace": [{
                "tool": "validate_static_site", "ok": False,
                "result": '{"verdict":"FAIL","errors":["missing asset"]}',
            }],
        }
        self.assertTrue(Orchestrator._has_failed_gate(state))


class PlanTests(unittest.TestCase):
    def test_simple_software_plan_is_capped_and_quality_roles_are_reserved(self) -> None:
        class VerbosePlanClient:
            def chat(self, **_kwargs):
                roles = ["researcher", "coder", "coder", "tester", "reviewer", "security_reviewer", "coder", "architect"]
                tasks = [
                    {"id": f"T{i}", "role": role, "task": f"work {i}", "depends_on": [], "needs_web": False}
                    for i, role in enumerate(roles, 1)
                ]
                return {"message": {"content": json.dumps({"goal": "fix", "task_type": "software", "tasks": tasks})}}

        agent = Orchestrator(Settings(max_agents=24, debate_rounds=2, repair_rounds=2), client=VerbosePlanClient())
        plan = agent.plan("landing page CSS sorununu düzelt")
        self.assertLessEqual(len(plan["tasks"]), 4)
        self.assertFalse({"tester", "reviewer", "security_reviewer"} & {item["role"] for item in plan["tasks"]})

    def test_dependencies_are_topologically_ordered(self) -> None:
        class PlanClient:
            def chat(self, **_kwargs):
                return {"message": {"content": json.dumps({
                    "goal": "read",
                    "tasks": [
                        {"id": "T2", "role": "architect", "task": "tasarla", "depends_on": ["T1"]},
                        {"id": "T1", "role": "researcher", "task": "araştır", "depends_on": []},
                    ],
                    "success_criteria": [],
                })}}

        agent = Orchestrator(Settings(), client=PlanClient())
        plan = agent.plan("dosyayı oku")
        self.assertEqual([task["id"] for task in plan["tasks"]], ["T1", "T2"])

    def test_plan_reserves_capacity_for_quality_and_repairs(self) -> None:
        class LargePlanClient:
            def chat(self, **_kwargs):
                tasks = [
                    {"id": f"T{i}", "role": "coder" if i == 1 else "market_researcher", "task": f"work {i}", "depends_on": [], "needs_web": i > 1}
                    for i in range(1, 10)
                ]
                return {"message": {"content": json.dumps({"goal": "x", "tasks": tasks, "success_criteria": ["done"]})}}

        agent = Orchestrator(Settings(max_agents=24, debate_rounds=2, repair_rounds=2), client=LargePlanClient())
        plan = agent.plan("build and research")
        self.assertEqual(len(plan["tasks"]), 6)
        self.assertIn("planner_warning", plan)


class SimpleAppOrchestrationTests(unittest.TestCase):
    def test_one_prompt_static_app_reaches_machine_verified_completion(self) -> None:
        class AppAgent(Orchestrator):
            def plan(self, user_task, write_allowed=None):
                return {
                    "goal": user_task, "task_type": "software", "debate_topics": [],
                    "success_criteria": ["responsive static page passes deterministic checks"],
                    "tasks": [{
                        "id": "T1", "role": "coder", "task": user_task,
                        "depends_on": [], "deliverable": "working page", "needs_web": False,
                        "acceptance": ["machine checks pass"],
                    }],
                }

            def chat_agent(self, role, _prompt, **_kwargs):
                if role == "coder":
                    files = {
                        "index.html": '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1">'
                        '<title>App</title><link rel="stylesheet" href="styles.css"></head>'
                        '<body><main><h1>Ready</h1></main><script src="app.js"></script></body></html>',
                        "styles.css": "body{margin:0}@media(max-width:40rem){main{padding:1rem}}",
                        "app.js": "document.documentElement.dataset.ready='true';",
                    }
                    for path, content in files.items():
                        result = write_file(path, content)
                        self.tool_trace.append({
                            "role": role, "tool": "write_file", "args": {"path": path},
                            "ok": True, "result": result,
                        })
                    return "Implemented and checked."
                if role in {"reviewer", "tester", "security_reviewer"}:
                    return "VERDICT: PASS"
                if role == "finalizer":
                    return "Completed."
                return "VERDICT: PASS"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(
                workspace=str(root), max_agents=8, debate_rounds=0,
                repair_rounds=0, agent_retries=0,
            )
            agent = AppAgent(settings, client=object())
            with patch("orchestrator.RUNS", root / "runs"):
                self.assertEqual(
                    agent.run_task("Build a responsive static landing page"), "Completed.",
                )
                state = json.loads((Path(agent.list_runs()[0]["path"]) / "state.json").read_text())
            self.assertEqual(state["status"], "completed")
            machine = [item for item in state["tool_trace"] if item["tool"] == "validate_static_site"]
            self.assertEqual(json.loads(machine[-1]["result"])["verdict"], "PASS")


class WorkspaceTests(unittest.TestCase):

    def test_isolated_writer_worktree_merges_through_clean_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.email", "test@modai.local"], cwd=root, check=True)
            subprocess.run(["git", "config", "user.name", "MODAI Test"], cwd=root, check=True)
            (root / "app.txt").write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "app.txt"], cwd=root, check=True)
            subprocess.run(["git", "commit", "-qm", "base"], cwd=root, check=True)
            isolated = IsolatedWorktree.create(root, "T1")
            try:
                (isolated.path / "app.txt").write_text("after\n", encoding="utf-8")
                patch_data = isolated.patch()
            finally:
                isolated.close()
            IsolatedWorktree.merge_into(root, patch_data)
            self.assertEqual((root / "app.txt").read_text(), "after\n")
            self.assertIn("app.txt", subprocess.run(
                ["git", "status", "--porcelain"], cwd=root, capture_output=True, text=True, check=True,
            ).stdout)

    def test_artifact_contract_blocks_missing_files_and_checks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            contract = infer_artifact_contract(
                "Create index.html and styles.css responsive landing page",
                {"tasks": []},
            )
            (root / "index.html").write_text("ready", encoding="utf-8")
            status = evaluate_artifact_contract(contract, root, [])
            self.assertEqual(status["verdict"], "FAIL")
            self.assertIn("styles.css", {item["path"] for item in status["files"] if item["status"] == "FAIL"})

    def test_shared_evidence_cache_invalidates_files_but_keeps_web(self) -> None:
        cache = EvidenceCache()
        cache.put("read_file", {"path": "a.txt"}, "file evidence")
        cache.put("fetch_url", {"url": "https://example.com"}, "web evidence")
        self.assertEqual(cache.get("read_file", {"path": "a.txt"}), "file evidence")
        cache.mark_workspace_changed()
        self.assertIsNone(cache.get("read_file", {"path": "a.txt"}))
        self.assertEqual(cache.get("fetch_url", {"url": "https://example.com"}), "web evidence")

    def test_browser_gate_covers_four_viewports_and_detects_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text(
                '<!doctype html><html><head><meta name="viewport" content="width=device-width"></head>'
                '<body style="margin:0"><main style="width:2000px"><h1>Wide</h1></main></body></html>',
                encoding="utf-8",
            )
            set_workspace(root)
            report = json.loads(validate_browser_quality())
            self.assertEqual(len(report["viewports"]), 4)
            self.assertEqual(report["verdict"], "FAIL")
            self.assertTrue(any("horizontal overflow" in error for item in report["viewports"] for error in item["errors"]))

    def test_smart_stop_hands_off_after_repeated_evidence(self) -> None:
        class RepeatingClient:
            def __init__(self):
                self.calls = 0

            def chat(self, **_kwargs):
                self.calls += 1
                if self.calls <= 3:
                    return {"message": {"content": "", "tool_calls": [{
                        "function": {"name": "read_file", "arguments": {"path": "a.txt"}},
                    }]}}
                return {"message": {"content": "Lead Arranger handoff", "tool_calls": []}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a.txt").write_text("same evidence", encoding="utf-8")
            client = RepeatingClient()
            agent = Orchestrator(Settings(workspace=str(root), max_tool_rounds=8), client=client)
            result = agent.chat_agent("researcher", "Inspect a.txt")
            self.assertEqual(result, "Lead Arranger handoff")
            self.assertTrue(any(item.get("cached") for item in agent.tool_trace))
            self.assertEqual(client.calls, 4)

    def test_live_score_contains_gates_tokens_files_and_efficiency(self) -> None:
        agent = Orchestrator(Settings(), client=object())
        state = {
            "plan": {"tasks": []}, "outputs": [], "artifact_contract": {},
            "artifact_status": {"files": [], "checks": [], "commands": []},
            "research_status": {"verdict": "SKIP"},
            "efficiency": {"changed_files": 2, "verified_units_per_10k_tokens": 1.5},
        }
        score = agent._score_text(state, "Code Virtuoso", "Test Percussionist")
        for label in ("SCORE", "NOW", "NEXT", "GATES", "TOKENS", "FILES", "EFF"):
            self.assertIn(label, score)

    def test_research_policy_rejects_uncited_external_claim(self) -> None:
        agent = Orchestrator(Settings(), client=object())
        state = {
            "artifact_contract": {"research": {
                "required": True, "minimum_sources": 1, "primary_source_required": True,
                "url_per_external_claim": True, "dates_required": True, "confidence_required": True,
            }},
            "outputs": [{
                "role": "market_researcher",
                "output": "Confidence: high. In 2026 the market reached 10 billion units without any cited evidence.",
            }],
        }
        status = agent._research_evidence_status(state)
        self.assertEqual(status["verdict"], "FAIL")
        self.assertEqual(len(status["uncited_external_claims"]), 1)
    def test_complete_static_landing_page_passes_machine_smoke_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "assets").mkdir()
            (root / "assets/logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"></svg>', encoding="utf-8")
            (root / "styles.css").write_text(
                "body{margin:0} main{max-width:70rem;margin:auto} @media (max-width:48rem){main{padding:1rem}}",
                encoding="utf-8",
            )
            (root / "app.js").write_text("document.documentElement.dataset.ready = 'true';", encoding="utf-8")
            (root / "index.html").write_text(
                '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>MODAI Demo</title><link rel="stylesheet" href="styles.css"></head>'
                '<body><main><h1>One prompt</h1><img src="assets/logo.svg" alt="MODAI"></main>'
                '<script src="app.js"></script></body></html>',
                encoding="utf-8",
            )
            set_workspace(root)
            report = json.loads(validate_static_site())
            self.assertEqual(report["verdict"], "PASS")
            self.assertEqual(report["errors"], [])

    def test_broken_static_app_fails_with_actionable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "styles.css").write_text("body{{color:red}", encoding="utf-8")
            (root / "index.html").write_text(
                '<html><head><link href="styles.css"><title></title></head>'
                '<body><main><h1 id="same">A</h1><p id="same">B</p>'
                '<img src="missing.svg"></main></body></html>',
                encoding="utf-8",
            )
            set_workspace(root)
            report = json.loads(validate_static_site())
            self.assertEqual(report["verdict"], "FAIL")
            evidence = "\n".join(report["errors"])
            self.assertIn("referenced local asset", evidence)
            self.assertIn("duplicate id", evidence)
            self.assertIn("viewport", evidence)
            self.assertIn("alt attribute", evidence)
            self.assertIn("Unbalanced CSS", evidence)

    def test_web_asset_validator_reports_only_referenced_missing_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "css").mkdir()
            (root / "images").mkdir()
            (root / "css/site.css").write_text("body{background:url('../images/missing.png')}")
            (root / "index.html").write_text(
                '<link href="css/site.css" rel="stylesheet"><img src="https://example.com/remote.png">',
                encoding="utf-8",
            )
            set_workspace(root)
            report = json.loads(validate_web_assets())
            self.assertEqual(report["verdict"], "FAIL")
            self.assertEqual(report["missing_count"], 1)
            self.assertEqual(report["missing"][0]["target"], "images/missing.png")

            (root / "images/missing.png").write_bytes(b"png")
            self.assertEqual(json.loads(validate_web_assets())["verdict"], "PASS")

    def test_web_asset_validator_rejects_workspace_escape(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text('<img src="../../secret.png">', encoding="utf-8")
            set_workspace(root)
            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                validate_web_assets()

    def test_tools_follow_selected_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.txt").write_text("hello", encoding="utf-8")
            set_workspace(root)
            self.assertIn("sample.txt", list_files())
            self.assertIn("hello", read_file("sample.txt"))

    def test_safe_directory_creation_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            set_workspace(directory)
            make_directory("assets/icons")
            self.assertTrue((Path(directory) / "assets/icons").is_dir())


class WebTests(unittest.TestCase):
    def test_search_results_are_parsed_and_ranked(self) -> None:
        page = """
        <li class="b_algo"><h2><a href="https://unrelated.example">Other</a></h2><p>noise</p></li>
        <li class="b_algo"><h2><a href="https://docs.ollama.com/">Ollama documentation</a></h2><p>Official Ollama docs</p></li>
        """
        with patch("tools.web._download", return_value=page):
            result = search_web("Ollama documentation", 2)
        self.assertLess(result.index("docs.ollama.com"), result.index("unrelated.example"))


class WebToolTests(unittest.TestCase):
    def test_search_results_are_parsed(self) -> None:
        page = '<li class="b_algo"><h2><a href="https://docs.example/a">Example Docs</a></h2><p>Useful result</p></li>'
        set_internet_enabled(True)
        with patch("tools.web._download", return_value=page):
            result = search_web("example docs", 1)
        self.assertIn("https://docs.example/a", result)
        self.assertIn("Useful result", result)

    def test_web_can_be_disabled(self) -> None:
        set_internet_enabled(False)
        with self.assertRaises(PermissionError):
            fetch_url("https://example.com")
        set_internet_enabled(True)


class DashboardTests(unittest.TestCase):
    def test_terminal_ui_collapses_repeated_tool_events(self) -> None:
        output = StringIO()
        ui = TerminalUI(color=False, language="en")
        with redirect_stdout(output):
            ui.event("tool", "market_signal_scout: search_web")
            ui.event("tool", "market_signal_scout: search_web")
            ui.event("ok", "finished")
        rendered = output.getvalue()
        self.assertEqual(rendered.count("market_signal_scout: search_web"), 1)
        self.assertIn("×2", rendered)

    def test_start_task_is_one_prompt_local_first_even_when_cloud_is_configured(self) -> None:
        class FakeOrchestrator:
            def __init__(self):
                self.settings = Settings(cloud_enabled=True, cloud_model="cloud-model", language="en")
                self.calls = []

            def run_task(self, task, **kwargs):
                self.calls.append((task, kwargs))
                return "done"

        class FakeDashboard:
            language = "en"

            def __init__(self):
                self.choices = iter([0, 9])
                self.choose_calls = 0

            def choose(self, *_args, **_kwargs):
                self.choose_calls += 1
                return next(self.choices)

            def edit_task(self):
                return "Build a static landing page"

            def clear(self):
                return None

        agent = FakeOrchestrator()
        dashboard = FakeDashboard()
        with patch("builtins.input", return_value=""), redirect_stdout(StringIO()):
            dashboard_loop(agent, TerminalUI(color=False, language="en"), dashboard)
        self.assertEqual(dashboard.choose_calls, 2)
        self.assertEqual(agent.calls, [(
            "Build a static landing page", {"write_allowed": None, "allow_cloud": False},
        )])

    def test_macos_csi_and_ss3_arrow_sequences_are_decoded(self) -> None:
        self.assertEqual(decode_key(b"\x1b[A"), "up")
        self.assertEqual(decode_key(b"\x1b[B"), "down")
        self.assertEqual(decode_key(b"\x1bOA"), "up")
        self.assertEqual(decode_key(b"\x1bOB"), "down")

    def test_unknown_escape_sequence_does_not_close_menu(self) -> None:
        self.assertEqual(decode_key(b"\x1b[1;5A"), "up")
        self.assertEqual(decode_key(b"\x1b[999~"), "ignore")

    def test_arrow_navigation_selects_second_option(self) -> None:
        keys = iter(["down", "enter"])
        dashboard = Dashboard(color=False, key_reader=lambda: next(keys))
        with redirect_stdout(StringIO()):
            selected = dashboard.choose("test", [("one", ""), ("two", "")], show_logo=False)
        self.assertEqual(selected, 1)

    def test_ignored_key_does_not_close_menu(self) -> None:
        keys = iter(["ignore", "down", "enter"])
        dashboard = Dashboard(color=False, key_reader=lambda: next(keys))
        with redirect_stdout(StringIO()):
            selected = dashboard.choose("test", [("one", ""), ("two", "")], show_logo=False)
        self.assertEqual(selected, 1)

    def test_english_interface_copy_is_available(self) -> None:
        dashboard = Dashboard(color=False, language="en")
        self.assertIn("select", dashboard.t("choose_hint"))
        self.assertEqual(dashboard.t("directory"), "WORKING DIRECTORY")

    def test_frame_uses_explicit_carriage_returns(self) -> None:
        output = StringIO()
        with redirect_stdout(output):
            Dashboard._draw(["first", "second"])
        self.assertEqual(output.getvalue(), "\033[H\033[Jfirst\r\nsecond\r\n")

    def test_task_editor_inserts_at_cursor_without_deleting(self) -> None:
        events = iter([
            ("text", "helo"), ("left", ""), ("text", "l"), ("enter", ""),
        ])
        dashboard = Dashboard(color=False, language="en")
        with redirect_stdout(StringIO()):
            result = dashboard.edit_task(lambda: next(events))
        self.assertEqual(result, "hello")

    def test_task_editor_labels_and_preserves_multiline_paste(self) -> None:
        events = iter([("paste", "ilk satır\nikinci satır"), ("enter", "")])
        dashboard = Dashboard(color=False, language="tr")
        output = StringIO()
        with redirect_stdout(output):
            result = dashboard.edit_task(lambda: next(events))
        self.assertEqual(result, "ilk satır\nikinci satır")
        self.assertIn("Yapıştırılan metin", output.getvalue())

    def test_pasted_terminal_escape_codes_are_removed(self) -> None:
        self.assertEqual(_safe_pasted_text(b"safe\x1b[2Jtext"), "safetext")

    def test_directory_browser_enters_and_selects_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            child = Path(directory) / "child"
            child.mkdir()
            keys = iter(["down", "down", "enter", "enter"])
            dashboard = Dashboard(color=False, key_reader=lambda: next(keys))
            with redirect_stdout(StringIO()):
                selected = dashboard.select_directory(directory)
            self.assertEqual(selected, child.resolve())


class RoleTests(unittest.TestCase):
    def test_business_and_software_team_is_available(self) -> None:
        self.assertGreaterEqual(len(ROLES), 20)
        for role in {"business_strategist", "market_researcher", "financial_analyst", "coder", "tester", "critic"}:
            self.assertIn(role, ROLES)


class ResumeTests(unittest.TestCase):
    def test_legacy_simple_software_resume_consolidates_pending_plan(self) -> None:
        state = {
            "version": "3.4.0", "task": "index.html ve CSS hatalarını düzelt ve test et",
            "write_allowed": True, "task_cursor": 1,
            "plan": {
                "task_type": "software", "success_criteria": ["site works"],
                "tasks": [
                    {"id": "T1", "role": "researcher", "task": "inspect"},
                    {"id": "T2", "role": "security_reviewer", "task": "review"},
                    {"id": "T3", "role": "coder", "task": "css"},
                    {"id": "T4", "role": "reviewer", "task": "review"},
                ],
            },
        }
        agent = Orchestrator(Settings(), client=object())
        agent._migrate_resume_plan(state)
        self.assertEqual([task["role"] for task in state["plan"]["tasks"]], ["coder"])
        self.assertEqual(state["task_cursor"], 0)
        self.assertEqual(state['phase'], 'execute')
        self.assertEqual(state["version"], "5.0.0")
        self.assertEqual(len(state['migration_history']), 1)

    def test_resume_allows_legacy_local_run_above_old_token_budget(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "expensive-run"
            run_dir.mkdir(parents=True)
            state = {
                "status": "paused", "phase": "execute", "task": "x",
                "workspace": str(root), "outputs": [],
                "usage": {"input_tokens": 900, "output_tokens": 200, "requests": 1, "cloud_requests": 0},
            }
            (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")
            agent = Orchestrator(Settings(workspace=str(root), max_total_tokens=1000), client=object())

            with patch("orchestrator.RUNS", root / "runs"), patch.object(agent, "_continue", return_value="resumed"):
                self.assertEqual(agent.resume("expensive-run"), "resumed")
                self.assertEqual(agent.usage["cloud_input_tokens"], 0)

    def test_legacy_completed_run_with_failed_gate_is_offered_for_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run_dir = root / "runs" / "legacy-run"
            run_dir.mkdir(parents=True)
            state = {
                "status": "completed",
                "phase": "completed",
                "task": "build the site",
                "workspace": str(root),
                "updated_at": "2026-09-13T23:00:00",
                "outputs": [
                    {"role": "reviewer", "output": "VERDICT: FAIL"},
                    {"role": "tester", "output": "VERDICT: PASS"},
                ],
            }
            (run_dir / "state.json").write_text(json.dumps(state), encoding="utf-8")

            with patch("orchestrator.RUNS", root / "runs"):
                listed = Orchestrator.list_runs()

            self.assertEqual(listed[0]["status"], "needs_attention")
            self.assertEqual(listed[0]["phase"], "blocked")

    def test_interrupted_run_resumes_from_checkpoint(self) -> None:
        class CheckpointAgent(Orchestrator):
            interrupt_once = True

            def plan(self, _task, write_allowed=None):
                return {
                    "goal": "x", "task_type": "research", "debate_topics": [],
                    "success_criteria": ["done"],
                    "tasks": [{
                        "id": "T1", "role": "researcher", "task": "inspect", "depends_on": [],
                        "deliverable": "answer", "needs_web": False, "acceptance": ["done"],
                    }],
                }

            def chat_agent(self, role, _prompt):
                if role == "researcher" and self.interrupt_once:
                    self.interrupt_once = False
                    raise KeyboardInterrupt
                if role in {"fact_checker", "reviewer", "tester", "security_reviewer"}:
                    return "VERDICT: PASS"
                if role == "finalizer":
                    return "finished"
                return "done"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(workspace=str(root), debate_rounds=0, repair_rounds=0, max_agents=8)
            agent = CheckpointAgent(settings, client=object())
            with patch("orchestrator.RUNS", root / "runs"):
                with self.assertRaises(KeyboardInterrupt):
                    agent.run_task("task")
                run = agent.list_runs()[0]
                self.assertEqual(run["status"], "paused")
                result = agent.resume(run["id"])
                self.assertEqual(result, "finished")
                self.assertEqual(agent.list_runs()[0]["status"], "completed")

    def test_failed_quality_gate_is_not_marked_completed(self) -> None:
        class FailingGateAgent(Orchestrator):
            def plan(self, _task, write_allowed=None):
                return {
                    "goal": "x", "task_type": "software", "debate_topics": [],
                    "success_criteria": ["works"],
                    "tasks": [{"id": "T1", "role": "architect", "task": "inspect", "depends_on": [], "deliverable": "report", "needs_web": False, "acceptance": ["works"]}],
                }

            def chat_agent(self, role, _prompt):
                if role in {"reviewer", "tester", "security_reviewer"}:
                    return "VERDICT: FAIL"
                return "not complete" if role == "finalizer" else "done"

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            settings = Settings(workspace=str(root), debate_rounds=0, repair_rounds=0, max_agents=10)
            agent = FailingGateAgent(settings, client=object())
            with patch("orchestrator.RUNS", root / "runs"):
                agent.run_task("task")
                state = json.loads((Path(agent.list_runs()[0]["path"]) / "state.json").read_text())
            self.assertEqual(state["status"], "needs_attention")
            self.assertEqual(state["phase"], "blocked")
            self.assertFalse(state["quality_passed"])


if __name__ == "__main__":
    unittest.main()
