from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from config import Settings
from contracts import artifact_fingerprints, evaluate_artifact_contract
from orchestrator import Orchestrator
from review_policy import normalize_review, security_review_needed
from runtime_context import set_workspace
from task_context import bounded_messages
from tools.browser_gate import validate_browser_quality


class EvidencePolicyTests(unittest.TestCase):
    def test_visual_review_sends_images_only_to_local_model_without_tools(self):
        class VisionClient:
            def chat(self, **kwargs):
                self.request = kwargs
                return {'message': {'content': '{"blocking_issues":[],"advisory":[]}'}}
        client = VisionClient()
        agent = Orchestrator(Settings(), client=client)
        agent._direct_task = True
        agent.chat_agent('reviewer', 'Review the current screenshots', images=['/tmp/mobile.png', '/tmp/desktop.png'])
        self.assertEqual(client.request['messages'][1]['images'], ['/tmp/mobile.png', '/tmp/desktop.png'])
        self.assertNotIn('tools', client.request)
        self.assertEqual(client.request['format'], 'json')
        agent.settings.browser_quality_gate = False
        self.assertIsNone(agent._review_images({}))

    def test_large_write_exchange_remembers_success_not_payload(self):
        messages = [
            {'role': 'system', 'content': 'Implement'}, {'role': 'user', 'content': 'Build index.html'},
            {'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'write_file', 'arguments': {'path': 'index.html', 'content': 'x' * 20000}}}]},
            {'role': 'tool', 'tool_name': 'write_file', 'content': 'Wrote index.html (20000 bytes)'},
        ]
        result = bounded_messages(messages, 8192, 2730)
        text = json.dumps(result)
        self.assertIn('Wrote index.html', text)
        self.assertNotIn('x' * 1000, text)
        self.assertNotEqual(result[-1]['role'], 'tool')

    def test_existing_artifact_is_not_evidence_of_implementation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'index.html'
            file.write_text('old site')
            contract = {'files': [{'path': 'index.html'}]}
            baseline = artifact_fingerprints(contract, root)
            self.assertEqual(evaluate_artifact_contract(contract, root, [], baseline, True)['verdict'], 'FAIL')
            self.assertEqual(evaluate_artifact_contract(contract, root, [], baseline, False)['verdict'], 'PASS')
            file.write_text('new site')
            self.assertEqual(evaluate_artifact_contract(contract, root, [], baseline, True)['verdict'], 'PASS')

    def test_resume_permission_provenance_and_explicit_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = {'version': '4.1.0', 'status': 'paused', 'phase': 'plan', 'task': 'Build a landing page',
                    'workspace': directory, 'write_allowed': False, 'plan': None, 'outputs': []}
            agent = Orchestrator(Settings(workspace=directory), client=object())
            for source, override, expected in [('inferred', None, True), ('explicit', None, False), (None, None, False), (None, True, True)]:
                state = dict(base)
                if source:
                    state['write_permission_source'] = source
                (root / 'state.json').write_text(json.dumps(state))
                with patch.object(agent, '_resolve_run', return_value=root), patch.object(agent, '_continue', return_value='ok') as continued:
                    agent.resume('test', write_allowed=override)
                    restored = continued.call_args.args[1]
                    self.assertEqual(restored['write_allowed'], expected)
                    self.assertEqual(restored['plan']['tasks'][0]['role'], 'coder' if expected else 'architect')

    def test_advisory_and_historical_findings_do_not_trigger_repair(self):
        findings = [{'file': 'index.html', 'issue': issue, 'evidence': 'review', 'action': 'fix', 'kind': 'requirement'}
                    for issue in ['main landmark is missing', 'Unsafe file:///old/index.html load']]
        traces = [{'tool': 'validate_static_site', 'result': '{"verdict":"PASS","warnings":["index.html: main landmark is missing"]}'}]
        result = normalize_review(json.dumps({'blocking_issues': findings}), 'Build a landing page', traces)
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(len(result['advisory']), 2)
        explicit = normalize_review(json.dumps({'blocking_issues': findings[:1]}), 'Add a main landmark', traces)
        self.assertEqual(explicit['verdict'], 'FAIL')
        self.assertEqual(normalize_review('VERDICT: FAIL', '', [])['verdict'], 'NEEDS_ATTENTION')

    def test_security_review_is_risk_driven(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / 'index.html'
            file.write_text('<main>Static content</main>')
            self.assertFalse(security_review_needed(root))
            file.write_text('<form><input type="password"></form>')
            self.assertTrue(security_review_needed(root))

    def test_old_failed_repair_does_not_override_current_direct_gates(self):
        state = {'plan': {'execution_policy': 'direct'}, 'artifact_status': {'verdict': 'PASS'},
                 'required_verification': ['reviewer'], 'outputs': [
                     {'role': 'coder', 'status': 'failed', 'output': 'old failure'},
                     {'role': 'reviewer', 'status': 'completed', 'output': 'VERDICT: PASS'},
                 ]}
        self.assertFalse(Orchestrator._has_failed_gate(state))

    def test_browser_rejects_dead_menu_and_accepts_working_toggle(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            set_workspace(root)
            page = ('<html><head><meta name="viewport" content="width=device-width"><style>.links{display:none}</style></head>'
                    '<body><nav><button aria-label="Menu" ACTION>Menu</button><div id="links" class="links"><a href="#features">Features</a></div></nav>'
                    '<main id="features"><h1>Test site</h1></main></body></html>')
            (root / 'index.html').write_text(page.replace('ACTION', ''))
            failed = json.loads(validate_browser_quality())
            self.assertEqual(failed['verdict'], 'FAIL')
            (root / 'index.html').write_text(page.replace('ACTION', 'onclick="document.getElementById(\'links\').style.display=\'block\'"'))
            self.assertEqual(json.loads(validate_browser_quality())['verdict'], 'PASS')


if __name__ == '__main__':
    unittest.main()
