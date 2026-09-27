"""Sequential local-model timing matrix; no downloads or paid providers."""
import argparse
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', action='append', required=True, help='Installed Ollama model; repeat for comparison')
    parser.add_argument('--repeat', type=int, default=1)
    parser.add_argument('--repair-fixture', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if not 1 <= args.repeat <= 10:
        parser.error('--repeat must be between 1 and 10')
    root = args.output or Path(tempfile.mkdtemp(prefix='modai-model-matrix-'))
    root.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve().parents[1]/'tests/benchmark_local.py'
    results = []
    for n, model in enumerate(args.model):
        runs = []
        for repetition in range(args.repeat):
            report = root/f'model-{n}-run-{repetition}.json'
            argv = [sys.executable, str(script), '--model', model, '--no-visual-review', '--report', str(report)]
            if args.repair_fixture:
                argv.append('--repair-fixture')
            result = subprocess.run(argv, check=False)
            if result.returncode or not report.is_file():
                runs.append({'status':'benchmark_error','exit_code':result.returncode})
            else:
                runs.append(json.loads(report.read_text(encoding='utf-8')))
        passed = [r for r in runs if r.get('status') == 'completed' and r.get('verification',{}).get('verdict') == 'PASS']
        first = [r['first_write_seconds'] for r in passed if r.get('first_write_seconds') is not None]
        results.append({'model':model,'passed':len(passed),'attempts':len(runs),
                        'median_first_artifact_seconds':statistics.median(first) if first else None,
                        'median_wall_seconds':statistics.median(r['wall_seconds'] for r in passed) if passed else None,
                        'runs':runs})
    (root/'summary.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    print(json.dumps({'output':str(root),'models':results}, indent=2))


if __name__ == '__main__':
    main()
