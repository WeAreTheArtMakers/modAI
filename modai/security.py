"""Model-facing privacy checks and bounded diagnostic redaction; not an OS sandbox."""
from __future__ import annotations

import re
import os
import tempfile
from typing import Any
from pathlib import Path


PRIVACY_PROFILES = frozenset({'guarded', 'strict', 'legacy'})
_SENSITIVE_NAMES = frozenset({'.npmrc', '.pypirc', '.netrc', '.envrc', 'id_rsa', 'id_ed25519',
                              'credentials.json', 'service-account.json', 'known_hosts'})
_SENSITIVE_DIRS = frozenset({'.ssh', '.aws', '.gnupg', '.codex', '.modai', '.run'})
_KEY_ASSIGNMENT = re.compile(r'(?i)\b([a-z0-9_]*(?:password|passwd|secret|api[_-]?key|access[_-]?token|auth[_-]?token|authorization))\b(\s*[:=]\s*)([^\s,;]+)')
_TOKEN = re.compile(r'\b(?:sk|rk|pk)-[A-Za-z0-9_-]{16,}\b|\bAIza[0-9A-Za-z_-]{20,}\b')
_BEARER = re.compile(r'(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{12,}')
_PRIVATE_KEY = re.compile(r'-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----')


def sensitive_path(path: Path, workspace: Path, profile: str = 'guarded') -> bool:
    if profile == 'legacy':
        return False
    try:
        parts = path.resolve().relative_to(workspace.resolve()).parts
    except ValueError:
        return True
    for part in parts:
        name = part.lower()
        if name in _SENSITIVE_NAMES or name in _SENSITIVE_DIRS:
            return True
        if name == '.env' or name.endswith('.env') or (name.startswith('.env.') and name not in {'.env.example', '.env.sample', '.env.template'}):
            return True
        if name.endswith(('.pem', '.key', '.p12', '.pfx', '.p8', '.kdbx')):
            return True
        if profile == 'strict' and (name.startswith('.') and name not in {'.gitignore', '.editorconfig', '.github'}
                                    or any(term in name for term in ('secret', 'credential', 'password', 'token'))):
            return True
    return False


def redact(text: str) -> str:
    text = _PRIVATE_KEY.sub('[REDACTED PRIVATE KEY]', text)
    text = _TOKEN.sub('[REDACTED TOKEN]', text)
    text = _BEARER.sub('Bearer [REDACTED]', text)
    return _KEY_ASSIGNMENT.sub(lambda match: match.group(1) + match.group(2) + '[REDACTED]', text)


def redact_data(value: Any) -> Any:
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {key: redact_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_data(item) for item in value]
    return value


def secure_atomic_text(path: Path, content: str) -> None:
    """Replace one run artifact with a mode-0600 file, without following links."""
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{path.name}.', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
