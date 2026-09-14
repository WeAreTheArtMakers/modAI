"""Read explicitly supplied public references once, without shell downloads."""
from __future__ import annotations
import base64
import json
import re
from urllib.parse import urlparse
from tools.web import _download, fetch_url


def reference_urls(task: str) -> list[str]:
    return list(dict.fromkeys(url.rstrip('.,);]') for url in re.findall(r'https?://[^\s<>"\]]+', task)))[:2]


def fetch_reference(url: str) -> str:
    parsed = urlparse(url)
    parts = parsed.path.strip('/').split('/')
    if parsed.hostname == 'github.com' and len(parts) == 2 and all(re.fullmatch(r'[\w.-]+', part) for part in parts):
        # GitHub resolves the default branch, including repositories not using main.
        data = json.loads(_download(f'https://api.github.com/repos/{parts[0]}/{parts[1]}/readme', 150000))
        if data.get('encoding') != 'base64' or not isinstance(data.get('content'), str):
            raise ValueError('GitHub did not return a readable README')
        return base64.b64decode(data['content']).decode('utf-8', 'replace')[:12000]
    return fetch_url(url, max_chars=12000)
