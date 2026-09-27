"""Local visual calibration. No model, cloud or network required."""
import argparse
import json
import sys
import tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modai.quality.calibration import calibrate

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workspace', type=Path, help='Evaluate an existing index.html, or bundled fixtures by default')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    output = args.output or Path(tempfile.mkdtemp(prefix='modai-visual-'))
    roots = [args.workspace] if args.workspace else sorted((Path(__file__).resolve().parents[1] / 'tests/fixtures/visual').iterdir())
    reports = {root.name: calibrate(root, output/root.name) for root in roots}
    (output/'report.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(output), 'reports': reports}, indent=2))
    if not args.workspace:
        assert reports['broken']['verdict'] == 'ISSUES'
        assert all(reports[name]['verdict'] == 'NO_HEURISTIC_ISSUES' for name in ('editorial','technical'))

if __name__ == '__main__':
    main()
