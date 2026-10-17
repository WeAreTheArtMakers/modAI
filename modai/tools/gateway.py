"""Deny-by-default capability boundary for future MCP adapters; no transport here."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

from modai.security import redact_data


class ToolGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolEntry:
    identity: str
    capability: str  # read, write, external
    handler: Callable[[dict[str, Any]], Any]
    approval_required: bool = False
    external: bool = False


class ToolGateway:
    def __init__(self, *, allow_external: bool = False,
                 audit: Callable[[dict[str, str]], None] | None = None) -> None:
        self.allow_external = allow_external
        self.audit = audit or (lambda _event: None)
        self._entries: dict[str, ToolEntry] = {}

    def register(self, entry: ToolEntry) -> None:
        if entry.identity in self._entries or entry.capability not in {"read", "write", "external"}:
            raise ValueError("duplicate tool identity or invalid capability")
        self._entries[entry.identity] = entry

    def invoke(self, identity: str, args: dict[str, Any], *, granted: set[str],
               approved: bool = False) -> dict[str, Any]:
        entry = self._entries.get(identity)
        if entry is None or entry.capability not in granted or (entry.external and not self.allow_external):
            self.audit({"tool": identity, "verdict": "DENY", "reason": "capability"})
            raise ToolGatewayError("tool capability denied")
        if entry.approval_required and not approved:
            self.audit({"tool": identity, "verdict": "DENY", "reason": "approval"})
            raise ToolGatewayError("explicit user approval required")
        if not isinstance(args, dict):
            raise ToolGatewayError("tool arguments must be an object")
        digest = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
        try:
            value = entry.handler(args)
        except Exception as exc:
            self.audit({"tool": identity, "verdict": "ERROR", "reason": type(exc).__name__, "args_hash": digest})
            raise ToolGatewayError("tool failed; details withheld from model") from None
        self.audit({"tool": identity, "verdict": "PASS", "reason": "executed", "args_hash": digest})
        return {"untrusted": True, "tool": identity, "content": redact_data(value)}
