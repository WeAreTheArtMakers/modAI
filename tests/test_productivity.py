from __future__ import annotations

import json
import os
import pty
import termios
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from contracts import infer_artifact_contract, evaluate_artifact_contract
from evidence_cache import EvidenceCache
from orchestrator import Orchestrator, TerminalUI
from task_context import bounded_messages, clip
from runtime_context import set_workspace


class ProductivityTests(unittest.TestCase):
    def test_live_details_toggle_restores_real_terminal_attributes(self):
        from contextlib import redirect_stdout
        from io import StringIO
        master, slave = pty.openpty()
        try:
            original = termios.tcgetattr(slave)
            with os.fdopen(os.dup(slave), 'r') as stream, redirect_stdout(StringIO()), \
                    patch('orchestrator.sys.stdin', stream), patch('orchestrator.interactive_terminal', return_value=True):
                ui = TerminalUI(color=False, language='en')
                ui.event('detail', 'read_file · index.html')
                ui._start_activity('Code Virtuoso')
                try:
                    os.write(master, b'd')
                    deadline = time.monotonic() + 2
                    while not ui.expanded and time.monotonic() < deadline:
                        time.sleep(.02)
                    self.assertTrue(ui.expanded)
                finally:
                    ui._stop_activity()
            restored = termios.tcgetattr(slave)
            # Darwin may set its transient pending-input flag on tcsetattr.
            restored[3] &= ~getattr(termios, 'PENDIN', 0)
            original[3] &= ~getattr(termios, 'PENDIN', 0)
            self.assertEqual(restored, original)
        finally:
            os.close(master)
            os.close(slave)

    def test_simple_website_from_scratch_skips_planner(self):
        agent = Orchestrator(Settings(), client=object())
        self.assertEqual(agent.plan('Build a website from scratch')['execution_policy'], 'direct')
        self.assertEqual(clip('x' * 200, 0), '')
        self.assertLessEqual(len(clip('x' * 200, 30).encode()), 30)

    def test_native_tool_rejection_keeps_complete_json_fallback_schemas(self):
        class FallbackClient:
            def __init__(self):
                self.calls = []
            def chat(self, **kwargs):
                self.calls.append(kwargs)
                if 'tools' in kwargs:
                    raise RuntimeError('model does not support tools')
                return {'message': {'content': '{"tool":"list_files","args":{}}'}}
        client = FallbackClient()
        agent = Orchestrator(Settings(), client=client)
        agent._direct_task = True
        schemas = agent._schemas('coder')
        agent._chat_request([{'role': 'system', 'content': 'Use JSON tools'},
                             {'role': 'user', 'content': 'Build a site'}], schemas)
        fallback = client.calls[-1]
        self.assertNotIn('tools', fallback)
        self.assertIn(json.dumps(schemas, ensure_ascii=False), fallback['messages'][0]['content'])

    def test_readme_is_reference_not_deliverables_or_readonly_instruction(self):
        document = Path(__file__).parents[1].joinpath('README.md').read_text()
        prompt = 'MODAI için modern bir landing page oluştur. Ürün bilgisi: # MODAI\n' + document
        agent = Orchestrator(Settings(), client=object())
        plan = agent.plan(prompt)  # object has no chat method: zero planner calls.
        self.assertEqual(plan['execution_policy'], 'direct')
        self.assertEqual(plan['tasks'][0]['role'], 'coder')
        self.assertEqual([f['path'] for f in plan['artifact_contract']['files']], ['index.html'])
        self.assertTrue(agent._infer_write_allowed(prompt))

    def test_file_regex_never_truncates_json_to_js_and_excludes_nodejs(self):
        contract = infer_artifact_contract('Create config.json, state.json and app.js. Use Node.js.', {'tasks': []})
        self.assertEqual({f['path'] for f in contract['files']}, {'config.json', 'state.json', 'app.js'})

    def test_context_bound_preserves_tool_pairing(self):
        messages = [{'role': 'system', 'content': 'system'}, {'role': 'user', 'content': 'Build a site'}]
        for index in range(20):
            messages.extend([
                {'role': 'assistant', 'tool_calls': [{'function': {'name': 'read_file', 'arguments': {'path': f'{index}.html'}}}], 'content': ''},
                {'role': 'tool', 'tool_name': 'read_file', 'content': 'long result ' * 1500},
            ])
        bounded = bounded_messages(messages, 8192, 2000)
        self.assertLess(len(json.dumps(bounded).encode()), 6192)
        for index, item in enumerate(bounded):
            if item['role'] == 'tool':
                self.assertTrue(bounded[index-1].get('tool_calls'))
        self.assertIn('Build a site', bounded[1]['content'])

    def test_contract_requires_machine_pass_and_zero_exit_status(self):
        with tempfile.TemporaryDirectory() as directory:
            contract = {'files': [], 'checks': ['validate_static_site'], 'commands': [{'command': ['node', 'test.js']}]}
            traces = [
                {'tool': 'validate_static_site', 'ok': True, 'result': '{"verdict":"FAIL"}'},
                {'tool': 'run_terminal', 'ok': True, 'args': {'command': ['node', 'test.js']}, 'result': 'exit_code=1\nfailed'},
            ]
            self.assertEqual(evaluate_artifact_contract(contract, Path(directory), traces)['verdict'], 'FAIL')

    def test_cache_invalidates_external_file_edit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_workspace(root)
            path = root / 'file.txt'
            path.write_text('before')
            cache = EvidenceCache()
            cache.put('read_file', {'path': 'file.txt'}, 'before')
            path.write_text('after')
            self.assertIsNone(cache.get('read_file', {'path': 'file.txt'}))

    def test_fast_site_produces_files_before_audit_without_planner_or_debate(self):
        class ScriptedClient:
            def __init__(self):
                self.calls = []

            def chat(self, **kwargs):
                self.calls.append(kwargs)
                if len(self.calls) == 1:
                    return {'message': {'content': '', 'tool_calls': [{'function': {
                        'name': 'write_file', 'arguments': {'path': 'index.html', 'content':
                        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
                        '<meta name="viewport" content="width=device-width,initial-scale=1"><title>MODAI</title>'
                        '</head><body><main><h1>One model, many agents</h1></main></body></html>'},
                    }}]}}
                return {'message': {'content': '{"blocking_issues":[],"advisory":[]}', 'tool_calls': []}}

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            client = ScriptedClient()
            agent = Orchestrator(Settings(workspace=directory, think=True, debate_rounds=3, max_agents=12), client=client)
            with patch('orchestrator.RUNS', root / 'runs'):
                agent.run_task('Build a responsive MODAI landing page')
            state = json.loads(next((root / 'runs').glob('*/state.json')).read_text())
            self.assertEqual(state['status'], 'completed')
            self.assertEqual([item['role'] for item in state['outputs']], ['coder', 'reviewer'])
            self.assertEqual(state['tool_trace'][0]['tool'], 'write_file')
            self.assertTrue(all(call['think'] is False for call in client.calls))
            self.assertLessEqual(len(client.calls), 8)
            self.assertTrue(all(len(json.dumps(call['messages']).encode()) < 8192 for call in client.calls))

    def test_stream_reassembles_tools_content_and_final_usage(self):
        class StreamingClient:
            def chat(self, **kwargs):
                yield {'message': {'content': 'Hello '}}
                yield {'message': {'content': 'world', 'tool_calls': [{'function': {'name': 'list_files', 'arguments': {}}}]}, 'prompt_eval_count': 20, 'eval_count': 5}
        agent = Orchestrator(Settings(), client=object())
        response = agent._local_stream(StreamingClient(), {})
        self.assertEqual(response['message']['content'], 'Hello world')
        self.assertEqual(len(response['message']['tool_calls']), 1)
        self.assertEqual(response['eval_count'], 5)

    def test_menu_alternate_buffer_returns_to_output_without_clearing_screen(self):
        from io import StringIO
        from contextlib import redirect_stdout
        from tui import Dashboard
        output = StringIO()
        with patch('tui.interactive_terminal', return_value=True), redirect_stdout(output):
            Dashboard._alternate_active = False
            Dashboard._draw(['Menu'])
            Dashboard.clear()
        self.assertIn('\033[?1049h', output.getvalue())
        self.assertTrue(output.getvalue().endswith('\033[?1049l'))


if __name__ == '__main__':
    unittest.main()
