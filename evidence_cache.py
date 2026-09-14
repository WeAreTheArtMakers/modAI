from __future__ import annotations

import hashlib
import json
import time
from typing import Any


READ_ONLY_TOOLS = {
    "list_files", "search_files", "read_file", "file_exists", "search_web", "fetch_url",
    "git_status", "git_diff", "validate_web_assets", "validate_static_site",
}
WEB_CACHE_TOOLS = {"search_web", "fetch_url"}


class EvidenceCache:
    """Small run-local shared cache with workspace-revision invalidation."""

    def __init__(self, data: dict[str, Any] | None = None, max_entries: int = 128) -> None:
        self.data = data if isinstance(data, dict) else {}
        self.max_entries = max_entries
        self.workspace_revision = int(self.data.pop("_workspace_revision", 0) or 0)

    def key(self, tool: str, args: dict[str, Any]) -> str:
        revision = 0 if tool in WEB_CACHE_TOOLS else self.workspace_revision
        raw = json.dumps([tool, args, revision], ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def get(self, tool: str, args: dict[str, Any], ttl_seconds: int = 3600) -> str | None:
        if tool not in READ_ONLY_TOOLS:
            return None
        item = self.data.get(self.key(tool, args))
        if not isinstance(item, dict):
            return None
        if tool in WEB_CACHE_TOOLS and time.time() - float(item.get("at", 0)) > ttl_seconds:
            return None
        result = item.get("result")
        return result if isinstance(result, str) else None

    def put(self, tool: str, args: dict[str, Any], result: str) -> None:
        if tool not in READ_ONLY_TOOLS:
            return
        self.data[self.key(tool, args)] = {"at": time.time(), "result": result[:20000]}
        while len(self.data) > self.max_entries:
            oldest = min(self.data, key=lambda key: float(self.data[key].get("at", 0)))
            self.data.pop(oldest, None)

    def mark_workspace_changed(self) -> None:
        self.workspace_revision += 1
        for key in list(self.data):
            if isinstance(self.data[key], dict) and key:
                # Web entries use revision zero and remain reusable; file entries are
                # naturally unreachable after the revision changes.
                continue

    def export(self) -> dict[str, Any]:
        return {**self.data, "_workspace_revision": self.workspace_revision}
