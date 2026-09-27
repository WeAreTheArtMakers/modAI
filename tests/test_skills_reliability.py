from pathlib import Path
from unittest.mock import patch
import json
import sys

import pytest

from modai.skills import SkillRegistry, SkillRouter
from modai.skills.registry import BUILTIN
from modai.models.ollama import OllamaRuntime
from modai.models.base import ModelResponse, ToolCall
from modai.models.fake import ScriptedRuntime
from modai.core.harness import CodingHarness
from modai.core.context import ContextManager
from modai.tools.coding import CodingTools
from modai.tools.policy import ToolPolicy, Capabilities


@pytest.mark.parametrize('task,expected', [
    ('create a landing page', ['landing-page-design', 'frontend-engineering']),
    ('MODAI için modern responsive landpage oluştur', ['landing-page-design', 'frontend-engineering']),
    ('fix this Python traceback', ['repo-debugging', 'python-engineering']),
    ('research current Ethereum L2 fees', ['web3-engineering', 'web-research']),
    ('analyze current BTC funding and OI', ['finance-research', 'web-research']),
    ('change README heading', []),
])
def test_domain_routing(task, expected, tmp_path):
    assert SkillRouter().select(task, SkillRegistry(tmp_path, global_root=tmp_path/'empty')) == expected


def test_builtin_quality_and_reference_security(tmp_path):
    registry = SkillRegistry(tmp_path, global_root=tmp_path/'empty')
    assert len(registry.skills) == 9
    assert not registry.diagnostics
    for name, skill in registry.skills.items():
        body, digest = registry.load(name)
        assert len(body) < 10000 and len(digest) == 64
        assert '/Users/' not in body and 'API_KEY=' not in body
    registry.load('landing-page-design', 'references/typography.md')
    with pytest.raises(ValueError):
        registry.load('landing-page-design', '../../README.md')


def test_project_skill_requires_trust_and_override_diagnostic(tmp_path):
    root = tmp_path/'.modai/skills/landing-page-design'
    root.mkdir(parents=True)
    (root/'SKILL.md').write_text('---\nname: landing-page-design\ndescription: Project design guidance.\n---\nUse red.\n')
    assert SkillRegistry(tmp_path).skills['landing-page-design'].source == 'built-in'
    trusted = SkillRegistry(tmp_path, trust_project=True)
    assert trusted.skills['landing-page-design'].source == 'project'
    assert any('overrides' in d['detail'] for d in trusted.diagnostics)


def test_top_level_think_system_normalization_stream_and_empty_classification():
    class Client:
        def chat(self, **kwargs):
            self.kwargs = kwargs
            return iter([{'message': {'thinking': 'private'}},
                         {'message': {'content': 'OK'}, 'eval_count': 3, 'done_reason': 'stop'}])
    client = Client()
    response = OllamaRuntime(client, 'local', options={'think': False}).generate(
        [{'role':'system','content':'core'}, {'role':'user','content':'task'},
         {'role':'system','content':'skill'}], [])
    assert client.kwargs['think'] is False
    assert 'think' not in client.kwargs['options']
    assert [m['role'] for m in client.kwargs['messages']] == ['system','user']
    assert response.content == 'OK' and response.thinking == 'private'
    empty = OllamaRuntime._classify(ModelResponse(usage=response.usage))
    assert empty.error_code == 'EMPTY_VISIBLE_MODEL_RESPONSE'


def test_error_result_is_never_success_and_6634_char_file_is_accepted(tmp_path):
    events = []
    runtime = ScriptedRuntime([
        ModelResponse(tool_calls=[ToolCall('a','write',{'path':'notes.txt','content':'x'*17000})]),
        ModelResponse(tool_calls=[ToolCall('b','write',{'path':'notes.txt','content':'x'*6634})]),
        ModelResponse(content='Done')])
    agent = CodingHarness(runtime=runtime, workspace=tmp_path, run_dir=tmp_path/'.run',
        task='Write notes.txt', max_write_chars=16000, event=events.append)
    assert agent.run().status == 'completed'
    finished = [e for e in events if e.kind == 'tool_finished']
    assert finished[0].data['ok'] is False
    assert finished[1].data['ok'] is True
    assert (tmp_path/'notes.txt').stat().st_size == 6634


def test_skill_load_preserves_read_only_permissions(tmp_path):
    agent = CodingHarness(runtime=ScriptedRuntime([ModelResponse(content='Analysis')]),
        workspace=tmp_path, run_dir=tmp_path/'.run', task='Read-only frontend review', write_allowed=False)
    agent.run()
    assert 'write' not in {s['function']['name'] for s in agent.registry.schemas()}
    assert agent.active_skills


def test_compaction_preserves_project_skill_and_complete_tool_pairs():
    messages = [{'role':'system','content':'core'}, {'role':'system','content':'project policy'},
                {'role':'system','skill':'x','content':'skill instructions'}, {'role':'user','content':'objective'},
                {'role':'assistant','tool_calls':[{'id':'a'}],'content':''},
                {'role':'tool','tool_call_id':'a','content':'x'*10000},
                {'role':'user','content':'Current mobile menu failure'}]
    compacted = ContextManager(1000,256).compact(messages)
    text = json.dumps(compacted)
    assert 'project policy' in text and 'skill instructions' in text and 'Current mobile menu' in text
    assert not any(m.get('role') == 'tool' for m in compacted)


def test_python_commands_use_harness_interpreter(tmp_path):
    tools = CodingTools(tmp_path, ToolPolicy(Capabilities(write=True)), tmp_path/'.logs')
    with patch('modai.tools.coding.subprocess.run') as run:
        run.return_value.returncode = 0
        tools.bash(['python3','-m','pytest'])
        assert run.call_args.args[0][0] == sys.executable


def test_cloud_delegate_cannot_read_project_files(tmp_path):
    from modai.orchestration.delegation import ReadOnlyDelegate
    from modai.core.evidence import SharedEvidenceCache
    (tmp_path/'private.txt').write_text('PRIVATE_CONTENT_DO_NOT_SEND')
    runtime = ScriptedRuntime([
        ModelResponse(tool_calls=[ToolCall('x', 'read', {'path':'private.txt'})]),
        ModelResponse(content='Public comparison only')])
    runtime.provider = 'cloud'
    delegate = ReadOnlyDelegate(runtime, tmp_path, tmp_path/'.logs', SharedEvidenceCache())
    assert delegate.run('Compare public approaches')['memo'] == 'Public comparison only'
    assert 'PRIVATE_CONTENT_DO_NOT_SEND' not in json.dumps(runtime.requests)
    assert all(s['function']['name'] not in {'read', 'ls', 'grep', 'bash'} for s in runtime.requests[0]['tools'])


def test_browser_nested_failure_reaches_repair_context(tmp_path):
    from modai.quality.project import ProjectVerifier
    (tmp_path/'index.html').write_text('<h1>MODAI</h1>')
    payload = {'verdict':'FAIL', 'errors':[], 'viewports':[{'name':'mobile', 'errors':['menu does not open']}]}
    with patch('tools.static_site.validate_static_site', return_value='{"verdict":"PASS"}'), \
         patch('tools.browser_gate.validate_browser_quality', return_value=json.dumps(payload)):
        report = ProjectVerifier(tmp_path, 'Review this site', lambda *_: {}, False).verify([])
    assert report.verdict == 'FAIL'
    assert any('mobile: menu does not open' in e for e in report.errors)


def test_optional_visual_review_reports_unavailable_instead_of_pass(tmp_path):
    from modai.quality.visual import review
    result, response = review(ScriptedRuntime([]), tmp_path, 'Landing page')
    assert result['verdict'] == 'UNAVAILABLE' and response is None
