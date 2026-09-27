import json
from pathlib import Path
from unittest.mock import patch
import pytest
from modai.core.tool_phase import select_tools, successful_result
from modai.core.harness import CodingHarness
from modai.models.fake import ScriptedRuntime
from modai.models.base import ModelResponse, ToolCall
from modai.quality.project import ProjectVerifier
from modai.quality.test_plan import discover_commands, verification_hint
from modai.quality.calibration import contrast_ratio, calibrate


@pytest.mark.parametrize('repair,structural,force,mutated,fast,expected', [
    (False,False,False,False,False,None),
    (False,False,False,False,True,{'read','ls','write','load_skill'}),
    (False,False,False,True,True,None),
    (False,False,True,False,True,{'write'}),
    (True,False,True,False,True,{'read','grep','edit'}),
    (True,True,False,True,False,{'read','grep','edit','write'}),
])
def test_surface_phases(repair,structural,force,mutated,fast,expected):
    assert select_tools(repair=repair,structural=structural,force_write=force,
        mutated=mutated,bash_disabled=False,available={'read','bash','write'},fast_bootstrap=fast)==expected


def test_bash_circuit_restricts_full_and_repair_surface():
    assert select_tools(repair=False,structural=False,force_write=False,mutated=True,
        bash_disabled=True,available={'bash','read'}) == {'read'}


@pytest.mark.parametrize('value,ok', [({'error_code':'FAILED'},False),({'exit_code':5},False),
    ({'error':'bad'},False),({'changed':True},True),({'exit_code':0},True)])
def test_tool_outcomes(value,ok):
    assert successful_result(value)==ok


def test_js_tests_do_not_trigger_pytest(tmp_path):
    (tmp_path/'tests').mkdir()
    (tmp_path/'tests/app.test.js').write_text('')
    assert discover_commands(tmp_path)==[]
    assert 'do not invent pytest' in verification_hint(tmp_path,True)
    (tmp_path/'tests/test_app.py').write_text('')
    assert discover_commands(tmp_path)[0][0]=='pytest'


def test_lockfile_and_scripts_are_shared_with_verifier(tmp_path):
    (tmp_path/'package.json').write_text(json.dumps({'scripts':{'test':'vitest run','lint':'eslint .'}}))
    (tmp_path/'pnpm-lock.yaml').write_text('')
    commands = discover_commands(tmp_path)
    assert commands[0][1]==['pnpm','run','test']
    calls=[]
    verifier=ProjectVerifier(tmp_path,'Inspect',lambda argv,timeout: calls.append(argv) or {'exit_code':0},False)
    assert all(x.verdict=='PASS' for x in verifier._command_checks())
    assert calls==[argv for _,argv in commands]


@pytest.mark.parametrize('package', ['[]','{"scripts": []}','broken'])
def test_malformed_metadata_does_not_crash(tmp_path,package):
    (tmp_path/'package.json').write_text(package)
    assert discover_commands(tmp_path)==[]


def test_verify_capability_cannot_be_granted_by_schema(tmp_path):
    from modai.tools.registry import ToolRegistry
    from modai.tools.coding import CodingTools
    from modai.tools.policy import Capabilities,ToolPolicy
    registry=ToolRegistry(CodingTools(tmp_path,ToolPolicy(Capabilities(test=False)),tmp_path/'.logs'))
    registry.verify=lambda:{'verdict':'PASS'}
    assert 'verify' not in {s['function']['name'] for s in registry.schemas()}
    with pytest.raises(PermissionError): registry.execute('verify',{})


def test_fast_bootstrap_lifts_after_artifact_and_records_model_timing(tmp_path):
    html='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Test</title><main><h1>Test</h1><p>Local</p></main></html>'
    runtime=ScriptedRuntime([ModelResponse(tool_calls=[ToolCall('a','write',{'path':'index.html','content':html})]),ModelResponse(content='Done')])
    agent=CodingHarness(runtime=runtime,workspace=tmp_path,run_dir=tmp_path/'.run',
        task='Create a landing page',max_write_chars=16000,max_auto_skills=0)
    with patch('tools.static_site.validate_static_site',return_value='{"verdict":"PASS"}'),patch('tools.browser_gate.validate_browser_quality',return_value='{"verdict":"PASS"}'):
        result=agent.run()
    first={s['function']['name'] for s in runtime.requests[0]['tools']}
    second={s['function']['name'] for s in runtime.requests[1]['tools']}
    assert 'bash' not in first and {'write','read'} <= first
    assert {'bash','verify','edit'} <= second
    assert result.status=='completed' and result.metrics['model']=='scripted'
    assert result.metrics['first_artifact_seconds'] is not None


def test_contrast_measurements():
    assert contrast_ratio('rgb(0, 0, 0)','rgb(255, 255, 255)')==21
    assert contrast_ratio('rgb(255, 255, 255)','rgb(255, 255, 255)')==1
    assert contrast_ratio('rgba(0,0,0,.5)','rgb(255,255,255)') is None
    assert contrast_ratio('color(display-p3 1 0 0)','rgb(255,255,255)') is None


def test_static_verification_cache_invalidates_on_content_change(tmp_path):
    agent=CodingHarness(runtime=ScriptedRuntime([]),workspace=tmp_path,run_dir=tmp_path/'.run',
        task='Create a landing page',max_auto_skills=0)
    agent.coding_tools.write('index.html','<h1>Hello</h1>')
    with patch('tools.static_site.validate_static_site',return_value='{"verdict":"PASS"}'),patch('tools.browser_gate.validate_browser_quality',return_value='{"verdict":"PASS"}'):
        first=agent._verify()
        assert agent._verify() is first
        (tmp_path/'index.html').write_text('<h1>Changed</h1>')
        assert agent._verify().sequence==2
    (tmp_path/'linked-assets').symlink_to(tmp_path/'.run',target_is_directory=True)
    assert agent._verification_key() is None


def test_model_verification_response_is_compact_but_keeps_errors(tmp_path):
    agent=CodingHarness(runtime=ScriptedRuntime([]),workspace=tmp_path,run_dir=tmp_path/'.run',task='Inspect')
    agent.registry.verify=lambda:{'verdict':'FAIL','checks':[{'name':'browser','verdict':'FAIL',
        'errors':['broken #target'],'details':{'huge':'x'*10000}}]}
    result=agent.registry.execute('verify',{})
    assert result['checks'][0]['errors']==['broken #target']
    assert len(json.dumps(result))<1000 and not successful_result(result)


def test_invisible_nav_and_click_javascript_error_are_detected(tmp_path):
    from runtime_context import set_workspace
    from tools.browser_gate import validate_browser_quality
    (tmp_path/'index.html').write_text('''<!doctype html><html><meta name="viewport" content="width=device-width"><title>Broken</title><nav><a href="#hidden" style="display:none">Hidden</a><a href="#" onclick="document.querySelector('#')">Broken click</a></nav><main id="hidden"><h1>Page</h1><p>Content</p></main></html>''')
    set_workspace(tmp_path)
    report=json.loads(validate_browser_quality())
    assert report['verdict']=='FAIL'
    errors=str(report)
    assert 'hidden navigation has no reachable alternative' in errors
    assert 'javascript:' in errors


def test_model_matrix_aggregates_only_verified_completions(tmp_path,monkeypatch):
    import sys
    from types import SimpleNamespace
    from scripts import benchmark_models
    monkeypatch.setattr(sys,'argv',['benchmark_models','--model','local/test','--repeat','2','--output',str(tmp_path)])
    calls=[]
    def run(argv,check):
        report=Path(argv[argv.index('--report')+1])
        n=len(calls)
        calls.append(argv)
        report.write_text(json.dumps({'status':'completed' if n==0 else 'needs_attention',
            'verification':{'verdict':'PASS' if n==0 else 'FAIL'},'first_write_seconds':4,'wall_seconds':12}))
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(benchmark_models.subprocess,'run',run)
    benchmark_models.main()
    summary=json.loads((tmp_path/'summary.json').read_text())[0]
    assert summary['passed']==1 and summary['attempts']==2
    assert summary['median_first_artifact_seconds']==4
    assert all('--no-visual-review' in argv for argv in calls)


@pytest.mark.parametrize('name,expected',[('editorial','NO_HEURISTIC_ISSUES'),('technical','NO_HEURISTIC_ISSUES'),('broken','ISSUES')])
def test_visual_examples_and_negative_control(tmp_path,name,expected):
    root=Path(__file__).parent/'fixtures/visual'/name
    result=calibrate(root,tmp_path/'screens')
    assert result['verdict']==expected
    assert len(result['viewports'])==4
    assert all(Path(r['screenshot']).is_file() for r in result['viewports'])
    if name=='broken':
        assert result['viewports'][0]['contrast_failures']
        assert 'horizontal overflow' in result['viewports'][0]['issues']
