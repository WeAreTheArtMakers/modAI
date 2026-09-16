from __future__ import annotations

import json
import hashlib
from typing import Any

from modai.core.evidence import SharedEvidenceCache
from .coding import MODEL_WRITE_MAX_CHARS, CodingTools


SCHEMAS = [
    {"type": "function", "function": {"name": "read", "description": "Read a targeted line range from a UTF-8 file.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "end_line": {"type": "integer"}}, "required": ["path"]}}},
    {"type": "function", "function": {"name": "ls", "description": "List a bounded project tree.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "depth": {"type": "integer"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "find", "description": "Find files by glob.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "limit": {"type": "integer"}}}}},
    {"type": "function", "function": {"name": "grep", "description": "Search project text with ripgrep.", "parameters": {"type": "object", "properties": {"pattern": {"type": "string"}, "path": {"type": "string"}, "glob": {"type": "string"}, "limit": {"type": "integer"}}, "required": ["pattern"]}}},
    {"type": "function", "function": {"name": "write", "description": "Create or fully replace a text file with ONE bounded chunk (max 4000 chars). USE THIS to create index.html, styles.css, app.js, or any new/changed file. Do NOT use bash to create files. For larger files, write a small valid scaffold first, then continue with append/edit.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Relative path, e.g. 'index.html' or 'src/styles.css'"}, "content": {"type": "string", "maxLength": MODEL_WRITE_MAX_CHARS, "description": "File content. Maximum 4000 characters per model tool call. For larger files, create a valid scaffold and continue with additional bounded mutations."}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "append", "description": "Append a small bounded text chunk (max 4000 chars) to the END of an EXISTING text file. Use write() first to create/scaffold a new file; use edit for precise replacements; use append only when extending end-of-file content is appropriate.", "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "Relative path of an existing file"}, "content": {"type": "string", "maxLength": MODEL_WRITE_MAX_CHARS, "description": "Continuation chunk, max 4000 characters. Never creates a missing file."}}, "required": ["path", "content"]}}},
    {"type": "function", "function": {"name": "edit", "description": "Patch an existing file with exact-text replacements. Each 'old' must match exactly once.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "edits": {"type": "array", "items": {"type": "object", "properties": {"old": {"type": "string"}, "new": {"type": "string"}}, "required": ["old", "new"]}}}, "required": ["path", "edits"]}}},
    {"type": "function", "function": {"name": "bash", "description": "Run ONE allowlisted program as an argument array (NOT a shell string). Allowed programs: python3 pytest node npm npx go cargo make rg grep find ls pwd cat head tail wc git. Do NOT pass 'bash', 'sh', 'touch', 'echo', 'curl', 'mv', 'cp' — they are blocked. To create files use the write tool instead.", "parameters": {"type": "object", "properties": {"argv": {"type": "array", "items": {"type": "string"}, "description": "e.g. [\"ls\", \".\"] or [\"python3\", \"-m\", \"pytest\"] — never ['bash','-c','...']"}, "timeout": {"type": "integer"}}, "required": ["argv"]}}},
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

    def schemas(self, allowed_names: set[str] | None = None) -> list[dict[str, Any]]:
        """Return tool schemas filtered by policy.
        
        allowed_names: optional additional allowlist on top of policy — used by the
        harness to temporarily restrict the tool surface (exploration budget,
        repair-mode restriction, bash circuit-breaker).
        """
        return [
            schema for schema in SCHEMAS
            if self.tools.policy.allows(schema["function"]["name"])
            and (allowed_names is None or schema["function"]["name"] in allowed_names)
        ]

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
        # v4.1.3 model-tool boundary: a fully parsed write/append whose
        # content exceeds the advertised chunk size is rejected BEFORE any
        # filesystem mutation. Low-level CodingTools stay unbounded for
        # internal Python callers and fixtures.
        if name in {"write", "append"}:
            content = arguments.get("content", "")
            if isinstance(content, str) and len(content) > MODEL_WRITE_MAX_CHARS:
                return {
                    "error": (
                        "CONTENT_TOO_LARGE: model write chunk exceeds "
                        f"{MODEL_WRITE_MAX_CHARS} characters "
                        f"(actual {len(content)})."
                    ),
                    "error_code": "CONTENT_TOO_LARGE",
                    "retryable": False,
                    "path": str(arguments.get("path", "?")),
                    "max_chars": MODEL_WRITE_MAX_CHARS,
                    "actual_chars": len(content),
                    "instruction": (
                        "CONTENT_TOO_LARGE. Maximum model write chunk: "
                        f"{MODEL_WRITE_MAX_CHARS} characters. Create a smaller "
                        "valid scaffold or continuation chunk. Use append for "
                        "additional end-of-file content. Use edit for precise "
                        "replacements."
                    ),
                }
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
        # Normalise legacy or incorrect bash calls where the model passes a
        # plain string "command" key or wraps argv in a nested dict.
        if name == "bash":
            if "command" in arguments and "argv" not in arguments:
                # model passed {"command": "ls -la"} instead of {"argv": ["ls", "-la"]}
                cmd = str(arguments["command"]).strip()
                arguments = {"argv": cmd.split(), "timeout": arguments.get("timeout", 120)}
            elif isinstance(arguments.get("argv"), str):
                # model passed {"argv": "ls -la"} as a string
                arguments = {"argv": arguments["argv"].split(), "timeout": arguments.get("timeout", 120)}
        method = getattr(self.tools, name, None)
        if not callable(method):
            raise KeyError(f"unknown tool: {name}")
        result = method(**arguments)
        if cache_key:
            self.evidence.put(cache_key, result)
        return result

    @staticmethod
    def model_result(result: dict[str, Any], limit: int = 8_000) -> str:
        value = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        if len(value) <= limit:
            return value
        return value[:limit] + '\n{"truncated":true,"hint":"Use a narrower read, grep, or line range."}'
