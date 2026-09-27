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
    parser.add_argument('--model', default='mod-agent:latest')
    parser.add_argument('--task', default='Create a modern responsive MODAI landing page in index.html with inline CSS. Read PRODUCT.md for actual product facts. No fabricated claims, pricing or testimonials. Include navigation to #features, a clear install CTA and three actual features. Keep it lightweight; implement and validate it.')
    parser.add_argument('--no-visual-review', action='store_true')
    parser.add_argument('--repair-fixture', action='store_true', help='Repair an existing static page with a reproducible mobile overflow')
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix='modai-live-benchmark-'))
    # Reproducible facts, never a copy of private workspace data.
    root.joinpath('PRODUCT.md').write_text('''# MODAI
MODAI is a local terminal coding harness for Ollama. A persistent Code Virtuoso
reads, edits, tests and repairs files in the selected workspace. Auto mode uses
one coding session for simple tasks. Optional bounded read-only delegation helps
independent research. Turkish and English UI, local tokens unlimited, optional
cloud with per-task consent. Static checks and Playwright browser gates verify
mobile, landscape, tablet and desktop. No published pricing, customer counts,
performance guarantees or testimonials. Install: clone repository, ./setup.sh,
./install-command.sh; then run modai in the project folder.
''', encoding='utf-8')
    if args.repair_fixture:
        root.joinpath('index.html').write_text("""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MODAI</title><style>*{box-sizing:border-box}body{margin:0;font-family:system-ui}main{width:700px;padding:24px}h1{font-size:2rem}</style></head><body><nav><a href="#features">Features</a></nav><main><h1>MODAI local coding harness</h1><section id="features"><h2>Read, edit, verify</h2><p>One persistent local coding session.</p></section></main></body></html>""", encoding='utf-8')
        args.task = 'Fix the mobile horizontal overflow in this existing MODAI responsive landing page index.html. Preserve the content and use a precise edit rather than rewriting. Test it and finish.'
    print(f'Benchmark workspace: {root}', flush=True)
    started = time.monotonic()
    first_write = None

    def event(kind: str, message: str) -> None:
        nonlocal first_write
        if kind == 'ok' and 'FILES ' in message and first_write is None:
            first_write = time.monotonic() - started
        if kind not in {'activity_progress', 'score'}:
            print(f'{time.monotonic()-started:6.1f}s {kind}: {message}', flush=True)

    agent = Orchestrator(Settings(workspace=str(root), model=args.model, language='en',
                                  debate_rounds=0, repair_rounds=1, max_agents=12,
                                  agent_retries=0, internet_enabled=False,
                                  harness_mode='solo',
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
                      'changed_paths': state.get('changed_paths', []),
                      'verification': state.get('verification', {}),
                      'metrics': state.get('metrics', {})}, indent=2), flush=True)


if __name__ == '__main__':
    main()
