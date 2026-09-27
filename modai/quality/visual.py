"""One bounded visual review and at most one review after a design repair."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def review(runtime: Any, workspace: Path, task: str) -> tuple[dict[str, Any], Any]:
    client = getattr(runtime, 'client', None)
    if not callable(getattr(client, 'show', None)) or runtime.provider != 'local':
        return {'verdict': 'UNAVAILABLE', 'reason': 'Local vision capability not available'}, None
    try:
        info = client.show(runtime.model)
        capabilities = info.get('capabilities', []) if isinstance(info, dict) else getattr(info, 'capabilities', [])
        if 'vision' not in capabilities:
            return {'verdict': 'UNAVAILABLE', 'reason': 'Model advertises no vision capability'}, None
        images = [workspace/'.modai/browser'/f'{name}.png' for name in ('mobile', 'desktop')]
        if not all(p.is_file() for p in images):
            return {'verdict': 'UNAVAILABLE', 'reason': 'Screenshots missing'}, None
        response = runtime.generate([
            {'role': 'system', 'content': 'Review rendered web design using the supplied screenshots. Return strict JSON only. Do not invent product facts.'},
            {'role': 'user', 'images': [str(p) for p in images], 'content': (
                'Task: ' + task[:1800] + '\nEvaluate hierarchy, typography, spacing, contrast, mobile layout, CTA clarity and generic-template artifacts. '
                'Return {"verdict":"PASS" or "FAIL","score":0-10,"issues":[],"strengths":[],"blocking_changes":[]}. '
                'Only concrete visible defects are blocking; describe the element and correction.')}
        ], [], max_output_tokens=768)
        raw = response.content.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
        result = json.loads(raw)
        if not isinstance(result, dict) or result.get('verdict') not in {'PASS', 'FAIL'} or not isinstance(result.get('blocking_changes'), list):
            raise ValueError('Invalid visual review schema')
        return result, response
    except Exception as exc:
        return {'verdict': 'UNAVAILABLE', 'reason': f'{type(exc).__name__}: {exc}'}, None
