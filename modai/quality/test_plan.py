"""Discover executable checks, not speculative test commands or installations."""
from __future__ import annotations
import json
import sys
from pathlib import Path


def discover_commands(workspace: Path) -> list[tuple[str, list[str]]]:
    commands: list[tuple[str, list[str]]] = []
    package = workspace / 'package.json'
    if package.is_file():
        try:
            data = json.loads(package.read_text(encoding='utf-8'))
            scripts = data.get('scripts', {}) if isinstance(data, dict) else {}
        except (ValueError, OSError):
            scripts = {}
        if isinstance(scripts, dict):
            manager = ('pnpm' if (workspace / 'pnpm-lock.yaml').is_file() else
                       'yarn' if (workspace / 'yarn.lock').is_file() else
                       'bun' if any((workspace / p).is_file() for p in ('bun.lock', 'bun.lockb')) else 'npm')
            for name in ('test', 'lint', 'build'):
                if isinstance(scripts.get(name), str) and scripts[name].strip():
                    commands.append((f'{manager} {name}', [manager, 'run', name]))
    # A JS tests/ folder does not imply pytest. Inspect actual Python tests.
    if any(workspace.glob('test*.py')) or any((workspace / 'tests').rglob('test*.py')):
        commands.append(('pytest', [sys.executable, '-m', 'pytest', '-q']))
    if (workspace / 'go.mod').is_file():
        commands.append(('go test', ['go', 'test', './...']))
    if (workspace / 'Cargo.toml').is_file():
        commands.append(('cargo test', ['cargo', 'test']))
    return commands[:4]


def verification_hint(workspace: Path, static: bool) -> str:
    commands = discover_commands(workspace)
    return ('PROJECT CHECKS (harness runs these after completion):\n' +
            '\n'.join(f'{name}: {json.dumps(argv)}' for name, argv in commands) +
            ('\nStatic asset + mobile/landscape/tablet/desktop browser gates.' if static else '') +
            ('\nNo configured test suite; do not invent pytest/npm test or install tools.' if not commands else '') +
            '\nUse verify to run the configured gates now; do not repeat these through bash.')
