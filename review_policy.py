"""Concrete review findings; advisory taste and historical errors cannot trigger repair."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def security_review_needed(workspace: Path) -> bool:
    pattern = re.compile(r'<form\b|type\s*=\s*[\"\']password|localStorage|sessionStorage|fetch\s*\(|XMLHttpRequest|<script[^>]+src\s*=\s*[\"\'](?:https?:)?//', re.I)
    inspected = 0
    for directory, dirs, files in os.walk(workspace):
        dirs[:] = [name for name in dirs if name not in {'.git', '.modai', '.venv', 'node_modules', '__pycache__', 'runs'}]
        for name in files:
            if Path(name).suffix.lower() not in {'.html', '.js', '.mjs'}:
                continue
            path = (Path(directory) / name).resolve()
            if workspace.resolve() not in path.parents:
                continue
            inspected += 1
            with path.open(encoding='utf-8', errors='replace') as source:
                if pattern.search(source.read(500000)):
                    return True
            if inspected >= 80:
                return True  # Incomplete risk scan: keep the security reviewer.
    return False


def normalize_review(text: str, task: str, traces: list[dict[str, Any]], workspace: Path | None = None) -> dict[str, Any]:
    stripped = re.sub(r'^```(?:json)?\s*|\s*```$', '', text.strip())
    try:
        data = json.loads(stripped)
        if not isinstance(data, dict) or not isinstance(data.get('blocking_issues'), list):
            raise ValueError('Expected blocking_issues array')
    except (ValueError, TypeError):
        return {'verdict': 'NEEDS_ATTENTION', 'blocking_issues': [], 'advisory': ['Review did not return a valid structured result. No speculative repair was scheduled.']}
    warnings: list[str] = []
    for trace in traces:
        if trace.get('tool') == 'validate_static_site':
            try:
                warnings = json.loads(trace.get('result', '{}')).get('warnings', [])
            except (ValueError, TypeError):
                pass
    blocking, advisory = [], list(data.get('advisory', [])) if isinstance(data.get('advisory', []), list) else []
    for item in data['blocking_issues'][:8]:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ('file', 'issue', 'evidence', 'action')):
            return {'verdict': 'NEEDS_ATTENTION', 'blocking_issues': [], 'advisory': ['A blocking finding has no file, evidence or repair action.']}
        if workspace is not None:
            path = (workspace / item['file']).resolve()
            if workspace.resolve() not in path.parents or not path.is_file():
                return {'verdict': 'NEEDS_ATTENTION', 'blocking_issues': [], 'advisory': ['A reviewer named a file outside the current verified artifacts. No speculative file creation scheduled.']}
        issue = item['issue'].casefold()
        warning_only = any(str(warning).split(': ', 1)[-1].casefold() in issue for warning in warnings)
        mentions_main = bool(re.search(r'\bmain\b', issue))
        requires_main = bool(re.search(r'\bmain\b', task.casefold()))
        warning_only |= mentions_main and not requires_main and any('main landmark' in str(warning) for warning in warnings)
        if mentions_main and requires_main and item.get('kind') == 'requirement':
            warning_only = False
        if warning_only or item.get('kind') in {'taste', 'advisory', 'warning'}:
            advisory.append(item['issue'])
            continue
        # A quoted old file:// browser error is not a live security finding.
        if 'file://' in issue and 'file://' not in '\n'.join(str(t.get('result', '')) for t in traces):
            advisory.append('Historical browser error: ' + item['issue'])
            continue
        blocking.append(item)
    return {'verdict': 'FAIL' if blocking else 'PASS', 'blocking_issues': blocking,
            'advisory': advisory, 'scores': data.get('scores', {})}
