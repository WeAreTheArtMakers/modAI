from __future__ import annotations

import json
import hashlib
from typing import Any

from modai.core.evidence import SharedEvidenceCache
from .coding import CodingTools


SCHEMAS = [
    {"type": "function", "function": {"name": "read", "description": "Read a targeted line range from a UTF-8 file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "ls", "description": "List a bounded project tree.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "find", "description": "Find files by glob.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "grep", "description": "Search project text with ripgrep.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "write", "description": "Atomically create or replace one text file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit", "description": "Atomically apply precise exact-text replacements. Every old string must match once; all edits validate before writing.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "edits": {"type": "array", "items": {"type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}}, "required": ["old", "new"]}}}, "required": ["path", "edits"]}}},
    {"type": "function", "function": {"name": "bash", "description": "Run an allowlisted command as an argument array, never through a shell.", "parameters": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}}, "timeout": {"type": "integer"}}, "required": ["argv"]}}},
    {"type": "function", "function": {"name": "git", "description": "Run a read-only git subcommand.", "parameters": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}}}, "required": ["argv"]}}},
    {"type": "function", "function": {"name": "delegate", "description": "Ask one bounded read-only specialist to gather independent evidence. Use only when independent inspection materially helps.", "parameters": {"type": "object", "properties": {"task": {"type": "string"}, "focus": {"type": "string"}}, "required": ["task"]}}},
    {"type": "function", "function": {"name": "web_search", "description": "Search the public web. Prefer primary sources and include URLs in the final evidence.", "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "max_results": {"type": "integer"}}, "required": ["query"]}}},
    {"type": "function", "function": {"name": "fetch_url", "description": "Read one public HTTP(S) source with SSRF protections and bounded text.", "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_chars": {"type": "integer"}}, "required": ["url"]}}},
]


class ToolRegistry:
    def __init__(self, tools: CodingTools, delegate: Any | None = None,
                 evidence: SharedEvidenceCache | None = None) -> None:
        self.tools = tools
        self.delegate = delegate
        self.evidence = evidence or SharedEvidenceCache()

    def schemas(self) -> list[dict[str, Any]]:
        return [schema for schema in SCHEMAS if self.tools.policy.allows(schema["function"]["name"])]

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        # Accept persisted 4.x tool calls during session migration; new schemas
        # advertise only the compact 5.x names.
        if name == "write_file":
            name = "write"
        elif name == "read_file":
            name = "read"
        elif name == "list_files":
            name = "ls"
        elif name == "make_directory":
            if not self.tools.policy.capabilities.write:
                raise PermissionError("tool capability denied: make_directory")
            return self.tools.make_directory(**arguments)
        elif name == "replace_in_file":
            name = "edit"
            arguments = {"path": arguments.get("path", ""), "edits": [{
                "old": arguments.get("old_text", arguments.get("old", "")),
                "new": arguments.get("new_text", arguments.get("new", "")),
            }]}
        if not self.tools.policy.allows(name):
            raise PermissionError(f"tool capability denied: {name}")
        cache_key = ""
        if name == "read":
            target = self.tools._path(str(arguments.get("path", "")), must_exist=True)
            cache_key = "file:" + hashlib.sha256(target.read_bytes()).hexdigest() + ":" + json.dumps(arguments, sort_keys=True)
        elif name in {"web_search", "fetch_url"}:
            cache_key = "web:" + name + ":" + json.dumps(arguments, sort_keys=True)
        if cache_key:
            cached = self.evidence.get(cache_key)
            if cached is not None:
                return {**cached, "cached": True}
        if name == "delegate":
            if not callable(self.delegate):
                raise RuntimeError("delegate runtime is unavailable")
            result = self.delegate(**arguments)
            return result
        if name == "web_search":
            from tools.web import search_web
            result = {"content": search_web(**arguments)}
            self.evidence.put(cache_key, result)
            return result
        if name == "fetch_url":
            from tools.web import fetch_url
            result = {"content": fetch_url(**arguments)}
            self.evidence.put(cache_key, result)
            return result
        if name == "git":
            return self.tools.bash(["git", *list(arguments.get("argv", []))])
        method = getattr(self.tools, name, None)
        if not callable(method):
            raise KeyError(f"unknown tool: {name}")
        result = method(**arguments)
        if cache_key:
            self.evidence.put(cache_key, result)
        return result

    @staticmethod
    def model_result(result: dict[str, Any]) -> str:
        return json.dumps(result, ensure_ascii=False, separators=(",", ":"))
