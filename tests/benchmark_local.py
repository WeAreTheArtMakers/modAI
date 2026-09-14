"""Opt-in real Ollama benchmark; all writes stay in a new temporary workspace.

Run: .venv/bin/python tests/benchmark_local.py --model MODEL
This is separate from deterministic regression tests and uses no paid providers.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import Settings
from orchestrator import Orchestrator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', required=True)
    parser.add_argument('--task', default='Create index.html: a polished MODAI landing page with inline CSS, a navigation link to #features, a hero heading and three feature cards. Make it mobile responsive. Write the actual file and test it.')
    parser.add_argument('--no-visual-review', action='store_true')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='modai-live-benchmark-'))
    print(f'Benchmark workspace: {root}', flush=True)
    started = time.monotonic()
    first_write = None

    def event(kind: str, message: str) -> None:
        nonlocal first_write
        if kind == 'ok' and message.startswith('File written:') and first_write is None:
            first_write = time.monotonic() - started
        if kind not in {'activity_progress', 'score'}:
            print(f'{time.monotonic()-started:6.1f}s {kind}: {message}', flush=True)

    agent = Orchestrator(Settings(workspace=str(root), model=args.model, language='en',
                                  debate_rounds=0, repair_rounds=1, max_agents=12,
                                  agent_retries=0, internet_enabled=False,
                                  visual_review=not args.no_visual_review), event=event)
    try:
        with patch('orchestrator.RUNS', root / 'runs'):
            agent.run_task(args.task)
    except KeyboardInterrupt:
        print('Benchmark interrupted; reporting checkpoint instead of claiming completion.', flush=True)
    state = json.loads(next((root / 'runs').glob('*/state.json')).read_text())
    print(json.dumps({'workspace': str(root), 'first_write_seconds': first_write,
                      'wall_seconds': round(time.monotonic()-started, 2),
                      'status': state['status'], 'usage': state['usage'],
                      'artifact_status': state['artifact_status'],
                      'requests': state.get('request_metrics', [])}, indent=2), flush=True)


if __name__ == '__main__':
    main()
