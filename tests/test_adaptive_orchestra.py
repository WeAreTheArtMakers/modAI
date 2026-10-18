"""Deterministic acceptance for the staged one-writer orchestra."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from modai.core.harness import CodingHarness
from modai.models.base import ModelResponse, ToolCall, Usage
from modai.models.fake import ScriptedRuntime
from modai.orchestration.coordinator import AdaptiveOrchestra
from modai.orchestration.reviewer import ReadOnlyReviewer, ReviewError
from modai.orchestration.scheduler import (InferencePaused, LocalInferenceScheduler,
                                           ResourceSnapshot, effective_context, mac_resource_snapshot)
from modai.orchestration.task_index import RunIndex
from modai.tools.gateway import ToolEntry, ToolGateway, ToolGatewayError


def _call(number: int, name: str, **arguments) -> ToolCall:
    return ToolCall(str(number), name, arguments)


def _review(paths: list[str], findings: list[dict] | None = None) -> ModelResponse:
    return ModelResponse(content=json.dumps({"reviewed_files": paths,
        "summary": "Inspected actual changed files and current checks.",
        "findings": findings or []}), usage=Usage(20, 10))


def _orchestra(root: Path, responses: list[ModelResponse], task: str,
               *, network: bool = False, visual: bool = False, run_dir: Path | None = None):
    runtime = ScriptedRuntime(responses)
    scheduler = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot(16 * 1024**3, 50, "test"))
    run_dir = run_dir or root / '.run'
    harness = CodingHarness(runtime=scheduler, workspace=root, run_dir=run_dir, task=task,
                            network_enabled=network, visual_review_enabled=visual,
                            allow_project_commands=False, model_retries=0, retry_backoff_seconds=0)
    state = {"verification": {"verdict": "MISSING", "checks": []}, "changed_paths": []}
    progress = []
    coordinator = AdaptiveOrchestra(harness, scheduler, scheduler, task=task, workspace=root,
        run_dir=run_dir, state=state, network_enabled=network, privacy_profile='guarded',
        progress=lambda label, detail: progress.append((label, detail)), persist=lambda: None)
    return coordinator, runtime, harness, state, progress


def test_static_frontend_research_code_verify_review_and_final_gate(tmp_path: Path):
    html = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>Small Frontend</title><link rel="stylesheet" href="styles.css"></head>'
        '<body><main><h1>Small Frontend</h1><p>Responsive by design.</p></main>'
        '<script src="app.js"></script></body></html>')
    css = 'body{margin:0;font-family:sans-serif}main{max-width:70rem;padding:2rem;margin:auto}@media(max-width:40rem){main{padding:1rem}}'
    js = "document.documentElement.dataset.ready='true';\n"
    task = 'Build a small responsive frontend website after reviewing relevant design requirements.'
    (tmp_path / 'README.md').write_text('Requirements: semantic HTML, responsive CSS, local assets only.\n')
    coordinator, runtime, harness, state, progress = _orchestra(tmp_path, [
        ModelResponse(tool_calls=[_call(0, 'read', path='README.md', start_line=1, end_line=20)]),
        ModelResponse(content='Requirements: semantic HTML, viewport, responsive layout; no external sources offline.',
                      usage=Usage(15, 10)),
        ModelResponse(tool_calls=[_call(1, 'write', path='index.html', content=html)]),
        ModelResponse(tool_calls=[_call(2, 'write', path='styles.css', content=css)]),
        ModelResponse(tool_calls=[_call(3, 'write', path='app.js', content=js)]),
        ModelResponse(content='Implemented the responsive frontend.'),
        _review(['index.html', 'styles.css', 'app.js']),
    ], task, visual=True)
    result = coordinator.run()
    assert result.status == 'completed', result.final
    assert result.verification['verdict'] == 'PASS'
    assert {p.name for p in tmp_path.iterdir() if p.is_file()} >= {'index.html', 'styles.css', 'app.js'}
    assert [label for label, _ in progress] == ['RESEARCHING', 'CODING', 'VERIFYING', 'REVIEWING', 'VERIFYING', 'COMPLETED']
    assert 'RESEARCH HANDOFF' in json.dumps(runtime.requests[2]['messages'])
    assert not any(s['function']['name'] in {'write', 'edit', 'append'} for s in runtime.requests[0]['tools'])
    assert all(s['function']['name'] not in {'web_search', 'fetch_url'} for s in runtime.requests[0]['tools'])
    assert runtime.requests[-1]['tools'] == []  # reviewer has no mutation tool surface
    assert 'Responsive by design' in runtime.requests[-1]['messages'][1]['content']
    research = next(r for r in harness.session.records() if r.get('stage') == 'research')
    assert research['artifact']['sources'][0]['kind'] == 'local_file'
    assert harness.session.records()[-1]['type'] == 'orchestra_stage'
    with sqlite3.connect(tmp_path / '.run' / 'tasks.sqlite3') as db:
        assert db.execute("SELECT state FROM tasks WHERE id='final_verify'").fetchone()[0] == 'completed'
        assert db.execute('SELECT COUNT(*) FROM artifacts').fetchone()[0] == 3
    assert any(c['name'] == 'browser_quality' and c['verdict'] == 'PASS'
               for c in result.verification['checks'])
    if os.name == 'posix':
        assert (tmp_path / '.run' / 'tasks.sqlite3').stat().st_mode & 0o777 == 0o600


def test_review_finding_triggers_one_writer_repair_and_final_verification(tmp_path: Path):
    finding = {'severity': 'blocking', 'file': 'note.md', 'line': 1, 'issue': 'Content is incorrect'}
    coordinator, runtime, harness, _state, progress = _orchestra(tmp_path, [
        ModelResponse(content='Offline requirements: create the requested note; no web evidence.'),
        ModelResponse(tool_calls=[_call(1, 'write', path='note.md', content='bad\n')]),
        ModelResponse(content='First draft.'),
        _review(['note.md'], [finding]),
        ModelResponse(tool_calls=[_call(2, 'edit', path='note.md', edits=[{'old': 'bad', 'new': 'good'}])]),
        ModelResponse(content='Repaired note.'),
        _review(['note.md']),
    ], 'Build note.md with a correct result')
    result = coordinator.run()
    assert result.status == 'completed', result.final
    assert (tmp_path / 'note.md').read_text() == 'good\n'
    assert [label for label, _ in progress].count('REPAIRING') == 1
    assert result.verification['sequence'] >= 2
    assert sum(1 for request in runtime.requests if any(s['function']['name'] == 'write'
               for s in request['tools'])) >= 1
    assert result.metrics['local_inference_concurrency'] == 1


def test_recovery_skips_completed_research_and_keeps_first_mutation(tmp_path: Path):
    task = 'Build note.md'
    first, _runtime, harness, _state, _progress = _orchestra(tmp_path, [
        ModelResponse(content='Offline task requirements only.'),
        ModelResponse(tool_calls=[_call(1, 'write', path='note.md', content='kept\n')]),
        TimeoutError('scripted timeout'),
    ], task)
    result = first.run()
    assert result.status == 'needs_attention'
    assert (tmp_path / 'note.md').read_text() == 'kept\n'
    resumed, runtime, second_harness, _state, _progress = _orchestra(tmp_path, [
        ModelResponse(content='The existing note is complete.'),
        _review(['note.md']),
    ], task, run_dir=tmp_path / '.run')
    second_harness.coding_tools.mutated_paths.update(harness.coding_tools.mutated_paths)
    done = resumed.run(resume=True)
    assert done.status == 'completed', done.final
    assert (tmp_path / 'note.md').read_text() == 'kept\n'
    assert all('RESEARCH HANDOFF' not in json.dumps(req['messages']) for req in runtime.requests[:1]) is False
    assert not any(call.name == 'write' for response in runtime.responses
                   for call in getattr(response, 'tool_calls', []))


def _completed_note(tmp_path: Path):
    task = 'Build note.md'
    first, _runtime, harness, _state, _progress = _orchestra(tmp_path, [
        ModelResponse(content='Offline note requirements.'),
        ModelResponse(tool_calls=[_call(1, 'write', path='note.md', content='original\n')]),
        ModelResponse(content='Implemented note.md.'),
        _review(['note.md']),
    ], task)
    result = first.run()
    assert result.status == 'completed'
    return task, result, harness


def _resume_completed_note(tmp_path: Path, task: str, previous, previous_harness,
                           responses: list[ModelResponse]):
    resumed, runtime, harness, state, progress = _orchestra(tmp_path, responses, task,
                                                              run_dir=tmp_path / '.run')
    harness.coding_tools.mutated_paths.update(previous_harness.coding_tools.mutated_paths)
    harness.verifier.sequence = previous.verification['sequence']
    state['verification'] = previous.verification
    state['changed_paths'] = previous.changed_paths
    return resumed, runtime, harness, state, progress


def test_completed_stage_rechecks_changed_file_and_reviews_current_content(tmp_path: Path):
    task, previous, old_harness = _completed_note(tmp_path)
    (tmp_path / 'note.md').write_text('externally changed\n')
    resumed, runtime, _harness, _state, progress = _resume_completed_note(
        tmp_path, task, previous, old_harness, [_review(['note.md'])])
    result = resumed.run(resume=True)
    assert result.status == 'completed', result.final
    assert len(runtime.requests) == 1  # no research or coder replay; fresh reviewer only
    assert 'externally changed' in runtime.requests[0]['messages'][1]['content']
    assert any(label == 'REVIEWING' for label, _ in progress)
    assert result.verification['sequence'] > previous.verification['sequence']


def test_missing_output_never_reuses_completed_final_verification(tmp_path: Path):
    task, previous, old_harness = _completed_note(tmp_path)
    (tmp_path / 'note.md').unlink()
    resumed, runtime, _harness, _state, _progress = _resume_completed_note(
        tmp_path, task, previous, old_harness, [])
    result = resumed.run(resume=True)
    assert result.status == 'needs_attention'
    assert result.verification['verdict'] == 'FAIL'
    assert any(check['name'] == 'artifact_integrity' for check in result.verification['checks'])
    assert not runtime.requests  # never blindly rerun the writer
    assert not (tmp_path / 'note.md').exists()


def test_interrupted_review_resume_preserves_completed_write(tmp_path: Path):
    task = 'Build note.md'
    first, _runtime, harness, _state, _progress = _orchestra(tmp_path, [
        ModelResponse(content='Offline note requirements.'),
        ModelResponse(tool_calls=[_call(1, 'write', path='note.md', content='kept\n')]),
        ModelResponse(content='Implemented note.md.'), KeyboardInterrupt(),
    ], task)
    with pytest.raises(KeyboardInterrupt):
        first.run()
    assert (tmp_path / 'note.md').read_text() == 'kept\n'
    verification = next(record['report'] for record in reversed(harness.session.records())
                        if record.get('type') == 'verification')
    resumed, runtime, second_harness, state, _progress = _orchestra(tmp_path, [
        _review(['note.md']),
    ], task, run_dir=tmp_path / '.run')
    second_harness.coding_tools.mutated_paths.update(harness.coding_tools.mutated_paths)
    state['verification'] = verification
    result = resumed.run(resume=True)
    assert result.status == 'completed', result.final
    assert (tmp_path / 'note.md').read_text() == 'kept\n'
    assert len(runtime.requests) == 1
    assert runtime.requests[0]['tools'] == []


def test_scheduler_serializes_fifo_requests_and_reports_pressure():
    class SlowRuntime:
        provider, model, supports_native_tools = 'local', 'test', True

        def __init__(self):
            self.active = 0
            self.maximum = 0
            self.order = []
            self.lock = threading.Lock()

        def generate(self, messages, _tools, **_kwargs):
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
                self.order.append(messages[0]['content'])
            time.sleep(0.04)
            with self.lock:
                self.active -= 1
            return ModelResponse(content='done')

    runtime = SlowRuntime()
    scheduler = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot(16 * 1024**3, 50, 'test'))
    threads = []
    for number in range(4):
        thread = threading.Thread(target=scheduler.generate,
                                  args=([{'role': 'user', 'content': str(number)}], []))
        thread.start()
        threads.append(thread)
        time.sleep(0.005)
    for thread in threads:
        thread.join(2)
        assert not thread.is_alive()
    assert runtime.maximum == scheduler.max_observed_concurrency == 1
    assert runtime.order == ['0', '1', '2', '3']
    low = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot(16 * 1024**3, 2, 'test'))
    with pytest.raises(InferencePaused):
        low.generate([], [])
    assert low.paused_reason and runtime.maximum == 1
    assert effective_context(32768, 'extended', ResourceSnapshot(16 * 1024**3, 50, 'test'))[0] == 8192
    assert effective_context(16384, 'balanced', ResourceSnapshot(None, None))[0] == 8192


def test_scheduler_cancellation_and_queue_timeout():
    started = threading.Event()
    release = threading.Event()

    class Blocker:
        provider, model, supports_native_tools = 'local', 'test', True

        def generate(self, *_args, **_kwargs):
            started.set()
            release.wait(2)
            return ModelResponse(content='done')

    scheduler = LocalInferenceScheduler(Blocker(), wait_timeout=0.04,
        probe=lambda: ResourceSnapshot(16 * 1024**3, 50, 'test'))
    first = threading.Thread(target=scheduler.generate, args=([], []))
    first.start()
    assert started.wait(1)
    with pytest.raises(InferencePaused, match='timed out'):
        scheduler.generate([], [])
    scheduler.cancel()
    with pytest.raises(InferencePaused, match='cancelled'):
        scheduler.generate([], [])
    release.set()
    first.join(2)


def test_active_swap_pressure_pauses_but_allocated_swap_alone_does_not():
    runtime = ScriptedRuntime([ModelResponse(content='allowed'), ModelResponse(content='unknown telemetry')])
    snapshot = ResourceSnapshot(16 * 1024**3, 12, 'test',
                                swap_used_bytes=10 * 1024**3, swapout_pages_per_second=0)
    scheduler = LocalInferenceScheduler(runtime, probe=lambda: snapshot)
    assert scheduler.generate([], []).content == 'allowed'
    active = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot(
        16 * 1024**3, 12, 'test', swap_used_bytes=10 * 1024**3,
        swapout_pages_per_second=128))
    with pytest.raises(InferencePaused, match='swap'):
        active.generate([], [])
    critical = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot(
        16 * 1024**3, 6, 'test', swapout_pages_per_second=0))
    with pytest.raises(InferencePaused, match='free memory'):
        critical.generate([], [])
    unavailable = LocalInferenceScheduler(runtime, probe=lambda: ResourceSnapshot())
    assert unavailable.generate([], []).content == 'unknown telemetry'
    assert len(runtime.requests) == 2


def test_mac_resource_probe_reports_recent_swap_activity_separately_from_allocation():
    class Result:
        returncode = 0

        def __init__(self, stdout):
            self.stdout = stdout

    def command(argv, **_kwargs):
        if argv == ['sysctl', '-n', 'hw.memsize']:
            return Result(str(16 * 1024**3))
        if argv == ['memory_pressure', '-Q']:
            return Result('System-wide memory free percentage: 12%\n')
        if argv == ['sysctl', 'vm.swapusage']:
            return Result('vm.swapusage: total = 11264.00M used = 9000.00M free = 2264.00M')
        if argv == ['vm_stat', '-c', '2', '1']:
            return Result('free active swapouts\n100 200 500000\n90 210 128\n')
        raise AssertionError(argv)

    with patch('modai.orchestration.scheduler.sys.platform', 'darwin'), patch(
            'modai.orchestration.scheduler.subprocess.run', side_effect=command):
        snapshot = mac_resource_snapshot()
    assert snapshot.free_percent == 12
    assert snapshot.swap_used_bytes == 9000 * 1024**2
    assert snapshot.swapout_pages_per_second == 128


@pytest.mark.parametrize('bad', [
    ModelResponse(content='not JSON', usage=Usage(4, 2)),
    ModelResponse(content='', usage=Usage(4, 0)),
    ModelResponse(content='{"findings": []}', truncated=True, usage=Usage(4, 5)),
    ModelResponse(content=json.dumps({'reviewed_files': ['note.md'], 'summary': 'Inspected note.',
                                      'findings': [{'severity': 'blocking', 'issue': 'missing file ref'}]}),
                  usage=Usage(4, 8)),
])
def test_reviewer_retries_once_without_inventing_pass(tmp_path: Path, bad: ModelResponse):
    (tmp_path / 'note.md').write_text('real file\n')
    runtime = ScriptedRuntime([bad, _review(['note.md'])])
    reviewer = ReadOnlyReviewer(runtime, tmp_path, tmp_path / '.run')
    result = reviewer.review('Inspect note.md', ['note.md'], {'checks': [], 'verdict': 'PASS'})
    assert result['findings'] == []
    assert len(runtime.requests) == 2
    assert all(request['tools'] == [] for request in runtime.requests)
    assert result['_usage']['input_tokens'] >= bad.usage.input_tokens


def test_reviewer_two_invalid_responses_preserve_error_and_usage(tmp_path: Path):
    (tmp_path / 'note.md').write_text('real file\n')
    runtime = ScriptedRuntime([ModelResponse(content='invalid', usage=Usage(3, 2)),
                               ModelResponse(content='', usage=Usage(5, 1))])
    reviewer = ReadOnlyReviewer(runtime, tmp_path, tmp_path / '.run')
    with pytest.raises(ReviewError) as error:
        reviewer.review('Inspect note.md', ['note.md'], {'checks': [], 'verdict': 'PASS'})
    assert len(runtime.requests) == 2
    assert error.value.usage['input_tokens'] == 8


def test_orchestra_failed_review_is_needs_attention_with_code_preserved(tmp_path: Path):
    coordinator, runtime, _harness, _state, _progress = _orchestra(tmp_path, [
        ModelResponse(content='Offline note requirements.'),
        ModelResponse(tool_calls=[_call(1, 'write', path='note.md', content='kept\n')]),
        ModelResponse(content='Implemented note.md.'),
        ModelResponse(content='bad review', usage=Usage(3, 2)),
        ModelResponse(content='', usage=Usage(5, 1)),
    ], 'Build note.md')
    result = coordinator.run()
    assert result.status == 'needs_attention'
    assert 'review' in result.final
    assert (tmp_path / 'note.md').read_text() == 'kept\n'
    assert result.metrics['orchestra_stages']['code'] == 'completed'
    assert result.usage['local_tokens'] >= 11


def test_task_index_skips_sensitive_artifacts_and_replays_jsonl(tmp_path: Path):
    from modai.core.session import SessionStore

    run = tmp_path / '.run'
    (tmp_path / 'note.md').write_text('safe')
    (tmp_path / '.env').write_text('API_KEY=private')
    index = RunIndex(run, tmp_path)
    index.record_artifacts(['note.md', '.env'])
    index.close()
    with sqlite3.connect(run / 'tasks.sqlite3') as db:
        assert db.execute('SELECT path FROM artifacts').fetchall() == [('note.md',)]
    store = SessionStore(run)
    store.append({'type': 'orchestra_stage', 'stage': 'research', 'state': 'completed',
                  'summary': 'bounded handoff', 'evidence_hash': 'a' * 64})
    store.append({'type': 'orchestra_stage', 'stage': 'code', 'state': 'completed',
                  'summary': 'changed files', 'artifact': {'paths': ['note.md', '.env'],
                  'hashes': {'note.md': 'b' * 64, '.env': 'c' * 64}}})
    (run / 'tasks.sqlite3').unlink()  # test-owned rebuildable index only
    rebuilt = RunIndex(run, tmp_path)
    rebuilt.recover(store.records())
    assert rebuilt.state('research') == 'completed'
    with sqlite3.connect(run / 'tasks.sqlite3') as db:
        assert db.execute('SELECT path, sha256 FROM artifacts').fetchall() == [('note.md', 'b' * 64)]
    rebuilt.close()


def test_task_index_detects_changed_and_deleted_artifact_hashes(tmp_path: Path):
    (tmp_path / 'note.md').write_text('first\n')
    index = RunIndex(tmp_path / '.run', tmp_path)
    hashes = index.record_artifacts(['note.md'])
    assert index.artifact_changes(['note.md']) == {}
    (tmp_path / 'note.md').write_text('second\n')
    assert index.artifact_changes(['note.md']) == {'note.md': 'changed'}
    assert index.artifact_changes(['note.md'], expected=hashes) == {'note.md': 'changed'}
    (tmp_path / 'note.md').unlink()
    assert index.artifact_changes(['note.md']) == {'note.md': 'missing'}
    index.close()


def test_gateway_mock_read_only_denies_write_and_external():
    events = []
    gateway = ToolGateway(audit=events.append)
    gateway.register(ToolEntry('mock.docs.read', 'read', lambda args: {'text': args['id']}))
    gateway.register(ToolEntry('mock.docs.write', 'write', lambda _args: 'bad', approval_required=True))
    gateway.register(ToolEntry('mock.external', 'external', lambda _args: 'bad', external=True))
    assert gateway.invoke('mock.docs.read', {'id': 'public'}, granted={'read'}) == {
        'untrusted': True, 'tool': 'mock.docs.read', 'content': {'text': 'public'}}
    with pytest.raises(ToolGatewayError):
        gateway.invoke('mock.docs.write', {}, granted={'read'})
    with pytest.raises(ToolGatewayError):
        gateway.invoke('mock.external', {}, granted={'external'}, approved=True)
    assert [event['verdict'] for event in events] == ['PASS', 'DENY', 'DENY']


def test_project_scripts_need_explicit_orchestra_trust(tmp_path: Path):
    from modai.quality.project import ProjectVerifier

    (tmp_path / 'package.json').write_text('{"scripts":{"test":"echo untrusted"}}')
    calls = []
    verifier = ProjectVerifier(tmp_path, 'Review this project', lambda argv, timeout: calls.append(argv) or
                               {'exit_code': 0}, write_allowed=False, allow_project_commands=False)
    report = verifier.verify([])
    assert report.verdict == 'FAIL'
    assert calls == []
    assert report.checks[0].name == 'project_commands'


def test_orchestrator_explicit_mode_uses_staged_pipeline_and_auto_stays_solo(tmp_path: Path):
    from config import Settings
    from orchestrator import Orchestrator

    class ChatClient:
        def __init__(self, responses):
            self.responses = list(responses)
            self.requests = []

        def chat(self, **kwargs):
            self.requests.append(kwargs)
            return self.responses.pop(0)

    def raw(content='', call=None):
        message = {'content': content, 'tool_calls': []}
        if call is not None:
            name, arguments = call
            message['tool_calls'] = [{'id': 'c', 'function': {'name': name, 'arguments': arguments}}]
        return {'message': message, 'prompt_eval_count': 4, 'eval_count': 3}

    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    review = json.dumps({'reviewed_files': ['note.md'], 'summary': 'Inspected current note and checks.',
                         'findings': []})
    client = ChatClient([
        raw('Offline requirements: create note.md; no public sources.'),
        raw(call=('write', {'path': 'note.md', 'content': 'ready\n'})),
        raw('Implemented note.md.'), raw(review),
    ])
    settings = Settings(workspace=str(workspace), harness_mode='orchestra', internet_enabled=False,
                        visual_review=False, repair_rounds=0)
    agent = Orchestrator(settings, client=client,
                         resource_probe=lambda: ResourceSnapshot(16 * 1024**3, 50, 'mock'))
    with patch('orchestrator.RUNS', tmp_path / 'runs'):
        final = agent.run_task('Build note.md')
        run = agent.list_runs()[0]
        assert len(client.requests) == 4
        (workspace / 'note.md').write_text('external update\n')
        client.responses.append(raw(review))
        resumed_final = agent.resume(run['id'])
    state = json.loads((Path(run['path']) / 'state.json').read_text())
    assert 'Adaptive Orchestra completed' in final
    assert 'Adaptive Orchestra completed' in resumed_final
    assert state['status'] == 'completed' and state['mode'] == 'orchestra'
    assert state['orchestra']['effective_context'] == 8192
    assert (workspace / 'note.md').read_text() == 'external update\n'
    assert len(client.requests) == 5  # completed run revalidated; writer was not replayed
    assert 'external update' in json.dumps(client.requests[-1]['messages'])
    assert (Path(run['path']) / 'tasks.sqlite3').is_file()

    for requested in ('solo', 'auto'):
        folder = tmp_path / requested
        folder.mkdir()
        simple = ChatClient([raw(call=('write', {'path': 'note.md', 'content': 'solo\n'})), raw('Done.')])
        agent = Orchestrator(Settings(workspace=str(folder), harness_mode=requested,
                                      internet_enabled=False, visual_review=False, repair_rounds=0), client=simple)
        with patch('orchestrator.RUNS', tmp_path / f'runs-{requested}'):
            agent.run_task('Build note.md')
            run_path = Path(agent.list_runs()[0]['path'])
            state = json.loads((run_path / 'state.json').read_text())
        assert state['mode'] == 'solo'
        assert not (run_path / 'tasks.sqlite3').exists()


@pytest.mark.parametrize('language,expected', [
    ('tr', '--workspace dizini bulunamadı'),
    ('en', '--workspace directory does not exist'),
])
def test_cli_rejects_missing_explicit_workspace_without_creating_it(tmp_path: Path,
                                                                      capsys, language: str, expected: str):
    from orchestrator import main

    missing = tmp_path / 'not-a-project'
    assert main(['--language', language, '--workspace', str(missing), 'Build a page']) == 1
    captured = capsys.readouterr()
    assert expected in captured.err
    assert 'Traceback' not in captured.err
    assert not missing.exists()
