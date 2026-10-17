"""Focused, fully mocked security and Groq compatibility checks."""
from __future__ import annotations

import io
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from config import Settings
from modai.core.session import SessionStore
from modai.models.ollama import OllamaRuntime
from modai.security import redact
from modai.tools.coding import CodingTools
from modai.tools.policy import Capabilities, ToolPolicy
from modai.tools.registry import ToolRegistry
from providers import CloudClient, CloudRequestError
from runtime_context import set_privacy_profile, set_workspace
from tool_registry import execute_tool
from tools.filesystem import read_file


def test_model_filesystem_blocks_secrets_but_direct_user_read_remains_available(tmp_path: Path):
    (tmp_path / '.env').write_text('API_KEY=private-value')
    (tmp_path / 'public.txt').write_text('public')
    set_workspace(tmp_path)
    set_privacy_profile('guarded')
    tools = CodingTools(tmp_path, ToolPolicy(Capabilities(write=True)), tmp_path / '.logs')
    registry = ToolRegistry(tools)
    with pytest.raises(PermissionError):
        registry.execute('read', {'path': '.env'})
    with pytest.raises(PermissionError):
        registry.execute('write', {'path': '.env', 'content': 'overwrite'})
    assert '.env' not in registry.execute('ls', {})['entries']
    with pytest.raises(PermissionError):
        execute_tool('read_file', {'path': '.env'}, ('read_file',))
    assert 'private-value' in read_file('.env')  # deliberate direct-user operation
    assert registry.execute('read', {'path': 'public.txt'})['content'].endswith('public')


def test_privacy_profile_legacy_is_explicit_compatibility_override(tmp_path: Path):
    (tmp_path / '.env').write_text('test')
    tools = CodingTools(tmp_path, ToolPolicy(Capabilities()), tmp_path / '.logs', privacy_profile='legacy')
    assert tools.read('.env')['content'].endswith('test')
    assert Settings(privacy_profile='legacy').privacy_profile == 'legacy'
    with pytest.raises(ValueError):
        Settings(privacy_profile='invalid').validate()


def test_session_keeps_resume_content_but_restricts_permissions(tmp_path: Path):
    run_dir = tmp_path / 'run'
    store = SessionStore(run_dir)
    store.append_message({'role': 'user', 'content': 'resume me'})
    assert store.messages()[0]['content'] == 'resume me'
    if os.name == 'posix':
        assert run_dir.stat().st_mode & 0o777 == 0o700
        assert store.path.stat().st_mode & 0o777 == 0o600
    if os.name == 'posix':
        store.path.chmod(0o644)
        resumed = SessionStore(run_dir)
        assert resumed.messages()[0]['content'] == 'resume me'
        assert store.path.stat().st_mode & 0o777 == 0o600


def test_command_timeout_log_is_scrubbed(tmp_path: Path):
    tools = CodingTools(tmp_path, ToolPolicy(Capabilities()), tmp_path / '.logs')

    def timeout(*_args, **kwargs):
        kwargs['stdout'].write(b'GROQ_API_KEY=top-secret\n')
        raise subprocess.TimeoutExpired('pytest', 1)

    with patch('modai.tools.coding.subprocess.run', side_effect=timeout):
        with pytest.raises(subprocess.TimeoutExpired):
            tools.bash(['pytest', '-q'])
    log = next((tmp_path / '.logs').glob('command-*.log'))
    assert 'top-secret' not in log.read_text()


def test_groq_native_tools_and_usage_normalize_without_network():
    client = CloudClient('groq', 'test-model')
    fixture = {'choices': [{'finish_reason': 'tool_calls', 'message': {'content': None,
        'tool_calls': [{'id': 'call_42', 'type': 'function',
            'function': {'name': 'web_search', 'arguments': '{"query":"public topic"}'}}]}}],
        'usage': {'prompt_tokens': 12, 'completion_tokens': 4}}
    schemas = [{'type': 'function', 'function': {'name': 'web_search', 'parameters': {'type': 'object'}}}]
    with patch('providers.api_key_for', return_value='fake'), patch.object(client, '_request', return_value=fixture) as req:
        response = OllamaRuntime(client, 'test-model', stream=False).generate(
            [{'role': 'user', 'content': 'public topic'}], schemas)
    assert req.call_args.args[0] == 'https://api.groq.com/openai/v1/chat/completions'
    assert req.call_args.args[1]['tools'] == schemas
    assert response.tool_calls[0].id == 'call_42'
    assert response.tool_calls[0].arguments == {'query': 'public topic'}
    assert response.usage.total_tokens == 16
    assert response.stop_reason == 'tool_calls'


def test_groq_length_and_invalid_tool_arguments():
    client = CloudClient('groq', 'test-model')
    with patch('providers.api_key_for', return_value='fake'), patch.object(client, '_request', return_value={
        'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}],
        'usage': {'prompt_tokens': 2, 'completion_tokens': 4}}):
        assert OllamaRuntime(client, 'test-model', stream=False).generate([], []).truncated
    with patch('providers.api_key_for', return_value='fake'), patch.object(client, '_request', return_value={
        'choices': [{'message': {'tool_calls': [{'function': {'name': 'read', 'arguments': '{bad'}}]}}]}):
        with pytest.raises(CloudRequestError, match='invalid_tool_arguments'):
            client.chat(messages=[], tools=[])


def test_unsupported_native_tools_fall_back_to_policy_checked_json():
    class Client:
        def __init__(self):
            self.calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if kwargs.get('tools'):
                raise CloudRequestError('groq', 'unsupported_tools')
            return {'message': {'content': json.dumps({'tool': 'read', 'args': {'path': '.env'}})}}

    client = Client()
    response = OllamaRuntime(client, 'test', stream=False).generate([], [{'type': 'function'}])
    assert client.calls == 2
    assert response.tool_calls[0].name == 'read'
    assert response.tool_calls[0].arguments == {'path': '.env'}  # parsed, not executed


def test_cloud_error_is_classified_without_response_body():
    client = CloudClient('groq', 'test')
    body = b'{"error":"API_KEY=top-secret"}'
    error = HTTPError('https://api.groq.com', 429, 'rate', {'Retry-After': '5'}, io.BytesIO(body))
    with patch('providers.urlopen', side_effect=error):
        with pytest.raises(CloudRequestError) as captured:
            client._request('https://api.groq.com', {}, {})
    assert captured.value.code == 'rate_limit'
    assert captured.value.retry_after == 5
    assert 'top-secret' not in str(captured.value)
    assert '[REDACTED]' in redact('API_KEY=top-secret')
    assert 'top-secret' not in redact('GROQ_API_KEY=top-secret')


def test_cloud_requires_network_and_cost_unknown_is_not_free(tmp_path: Path):
    from orchestrator import CloudBudgetPaused, Orchestrator

    settings = Settings(workspace=str(tmp_path), cloud_enabled=True, cloud_model='test', internet_enabled=False)
    agent = Orchestrator(settings, client=object())
    agent.cloud_client = object()
    with pytest.raises(PermissionError):
        agent._chat_request([{'role': 'user', 'content': 'public'}], use_cloud=True)
    assert not agent._cloud_task_eligible({'cloud_allowed': True},
        {'needs_web': True, 'role': 'market_researcher', 'task': 'public'})
    assert agent._cloud_cost_usd({'cloud_input_tokens': 100, 'cloud_output_tokens': 100}) is None
    settings.cloud_input_usd_per_million = 1.0
    settings.cloud_output_usd_per_million = 2.0
    assert agent._cloud_cost_usd({'cloud_input_tokens': 1_000_000, 'cloud_output_tokens': 1_000_000}) == 3.0
    settings.cloud_usd_limit = 0.5
    agent.usage['cloud_input_tokens'] = 500_000
    with pytest.raises(CloudBudgetPaused):
        agent._ensure_cloud_budget()


def test_cloud_delegate_discards_model_authored_private_focus(tmp_path: Path):
    from modai.core.evidence import SharedEvidenceCache
    from modai.models.base import ModelResponse
    from modai.models.fake import ScriptedRuntime
    from modai.orchestration.delegation import ReadOnlyDelegate

    runtime = ScriptedRuntime([ModelResponse(content='public evidence')])
    runtime.provider = 'cloud'
    delegate = ReadOnlyDelegate(runtime, tmp_path, tmp_path / '.logs', SharedEvidenceCache(),
                                network_enabled=True, public_task='Compare public tooling')
    assert delegate.run('PRIVATE_SOURCE_CODE', focus='API_KEY=private-value')['memo'] == 'public evidence'
    request = json.dumps(runtime.requests)
    assert 'PRIVATE_SOURCE_CODE' not in request and 'private-value' not in request
    assert 'Compare public tooling' in request
    blocked = ReadOnlyDelegate(runtime, tmp_path, tmp_path / '.logs2', SharedEvidenceCache(),
                               network_enabled=False, public_task='Compare public tooling')
    with pytest.raises(PermissionError):
        blocked.run('Compare public tooling')


def test_event_logs_redact_known_credentials():
    from modai.core.events import EventBus

    seen = []
    bus = EventBus()
    bus.subscribe(seen.append)
    bus.emit('tool_finished', result={'output': 'API_KEY=private-value'})
    assert 'private-value' not in json.dumps(seen[0].as_dict())
