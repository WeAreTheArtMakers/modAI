import base64
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from task_sources import fetch_reference, reference_urls


class TaskSourceTests(unittest.TestCase):
    def test_truncated_tool_response_changes_strategy(self):
        from config import Settings
        from orchestrator import Orchestrator
        class Client:
            def __init__(self): self.requests = []
            def chat(self, **kwargs):
                self.requests.append(kwargs)
                if len(self.requests) == 1:
                    return {'message': {'content': '{"tool":"write_file","args":{'}, 'done_reason': 'length'}
                return {'message': {'content': 'No changes needed'}}
        client = Client()
        agent = Orchestrator(Settings(), client=client)
        agent._direct_task = True
        agent.chat_agent('coder', 'Build a landing page')
        self.assertIn('small complete index.html', json.dumps(client.requests[1]['messages']))
        self.assertEqual(agent.tool_trace, [])

    def test_direct_run_prepares_source_once_and_resume_reuses_it(self):
        from config import Settings
        from orchestrator import Orchestrator
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            agent = Orchestrator(Settings(workspace=directory), client=object())
            with patch('orchestrator.RUNS', root / 'runs'), patch('orchestrator.fetch_reference', return_value='Verified local orchestra facts') as fetch, patch.object(agent, '_execute_planned', side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    agent.run_task('Build a landing page using https://github.com/acme/product/')
                run = next((root / 'runs').iterdir())
                state = json.loads((run / 'state.json').read_text())
                self.assertIn('Verified local orchestra facts', agent._task_prompt(state, state['plan']['tasks'][0]))
                with self.assertRaises(KeyboardInterrupt):
                    agent.resume(run.name)
                fetch.assert_called_once()

    def test_github_repository_uses_default_branch_readme_api(self):
        payload = json.dumps({'encoding': 'base64', 'content': base64.b64encode(b'# Product facts').decode()})
        with patch('task_sources._download', return_value=payload) as download:
            self.assertEqual(fetch_reference('https://github.com/WeAreTheArtMakers/modAI/'), '# Product facts')
        self.assertEqual(download.call_args.args[0], 'https://api.github.com/repos/WeAreTheArtMakers/modAI/readme')

    def test_other_urls_keep_safe_web_reader(self):
        with patch('task_sources.fetch_url', return_value='facts') as fetch:
            self.assertEqual(fetch_reference('https://example.com/product'), 'facts')
        fetch.assert_called_once_with('https://example.com/product', max_chars=12000)

    def test_urls_are_deduplicated_and_bounded(self):
        self.assertEqual(reference_urls('https://a.example/ https://a.example/ https://b.example/ https://c.example/'), ['https://a.example/', 'https://b.example/'])
