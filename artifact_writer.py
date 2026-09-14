"""Validate model-produced static artifacts before any filesystem mutation."""
from __future__ import annotations
import json
from pathlib import Path


def decode_artifacts(text: str, workspace: Path) -> list[dict[str, str]]:
    data = json.loads(text)
    files = data.get('files') if isinstance(data, dict) else None
    if not isinstance(files, list) or not 1 <= len(files) <= 4:
        raise ValueError('Return JSON files array with 1–4 complete static files, not a plan or tool request')
    names: set[str] = set()
    total = 0
    root = workspace.resolve()
    for item in files:
        if not isinstance(item, dict) or not all(isinstance(item.get(key), str) and item[key].strip() for key in ('path', 'content')):
            raise ValueError('Each artifact needs a nonempty path and complete content')
        path = Path(item['path'])
        target = (root / path).resolve()
        if path.is_absolute() or '..' in path.parts or root not in target.parents:
            raise ValueError('Artifact path escapes the workspace')
        if path.suffix.lower() not in {'.html', '.css', '.js', '.svg', '.md'} or any(part.startswith('.') for part in path.parts):
            raise ValueError('Only visible static-site artifact paths are allowed')
        if str(target) in names:
            raise ValueError('Duplicate artifact destination')
        names.add(str(target))
        total += len(item['content'].encode('utf-8'))
    if total > 160000:
        raise ValueError('Artifact response too large; return smaller complete files')
    if not (root / 'index.html').is_file() and str(root / 'index.html') not in names:
        raise ValueError('A new site must include index.html directly in the selected workspace')
    return files
