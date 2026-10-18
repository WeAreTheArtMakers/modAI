from __future__ import annotations

import json
import hashlib
from pathlib import Path, PureWindowsPath
from typing import Any
from modai.security import redact_data

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

ALIASES = {"write_file": "write", "read_file": "read",
           "list_files": "ls", "replace_in_file": "edit"}
EXAMPLES = {
    "write": {"path": "index.html", "content": "..."},
    "append": {"path": "index.html", "content": "..."},
    "edit": {"path": "index.html", "edits": [{"old": "before", "new": "after"}]},
    "read": {"path": "README.md"},
}


def _argument_issues(value: Any, schema: dict[str, Any], prefix: str = "") -> tuple[list[str], list[str]]:
    """Validate the advertised types/required fields without executing a tool."""
    kind = schema.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            return [], [prefix or "arguments"]
        properties = schema.get("properties", {})
        missing = [prefix + key for key in schema.get("required", []) if key not in value]
        invalid: list[str] = []
        for key, item in value.items():
            label = prefix + key
            if key not in properties:
                invalid.append(label)
            else:
                nested_missing, nested_invalid = _argument_issues(item, properties[key], label + ".")
                missing.extend(nested_missing)
                invalid.extend(nested_invalid)
        return missing, invalid
    if kind == "array":
        if not isinstance(value, list):
            return [], [prefix.rstrip(".")]
        missing, invalid = [], []
        for index, item in enumerate(value[:32]):
            nested_missing, nested_invalid = _argument_issues(
                item, schema.get("items", {}), f"{prefix}[{index}].")
            missing.extend(nested_missing)
            invalid.extend(nested_invalid)
        if len(value) > 32:
            invalid.append(prefix.rstrip("."))
        return missing, invalid
    valid = {"string": isinstance(value, str), "integer": type(value) is int,
             "number": type(value) in {int, float}, "boolean": type(value) is bool}.get(kind, True)
    return ([], [] if valid else [prefix.rstrip(".")])


class ToolRegistry:
    def __init__(self, tools: CodingTools, delegate: Any | None = None,
                 evidence: SharedEvidenceCache | None = None,
                 max_write_chars: int = MODEL_WRITE_MAX_CHARS,
                 load_skill: Any | None = None) -> None:
        self.tools = tools
        self.delegate = delegate
        self.evidence = evidence or SharedEvidenceCache()
        self.max_write_chars = max_write_chars
        self.load_skill = load_skill
        self.verify = None

    def schemas(self, allowed_names: set[str] | None = None) -> list[dict[str, Any]]:
        """Return tool schemas filtered by policy.
        
        allowed_names: optional additional allowlist on top of policy — used by the
        harness to temporarily restrict the tool surface (exploration budget,
        repair-mode restriction, bash circuit-breaker).
        """
        import copy
        schemas = copy.deepcopy([
            schema for schema in SCHEMAS
            if self.tools.policy.allows(schema["function"]["name"])
            and (allowed_names is None or schema["function"]["name"] in allowed_names)
        ])
        for schema in schemas:
            fn = schema['function']
            if fn['name'] in {'write', 'append'}:
                fn['description'] = fn['description'].replace('4000', str(self.max_write_chars))
                prop = fn['parameters']['properties']['content']
                prop['maxLength'] = self.max_write_chars
                prop['description'] = prop['description'].replace('4000', str(self.max_write_chars))
        if self.load_skill and (allowed_names is None or 'load_skill' in allowed_names):
            schemas.append({'type': 'function', 'function': {'name': 'load_skill',
                'description': 'Activate domain instructions by skill name; optional reference is relative to that skill.',
                'parameters': {'type': 'object', 'properties': {'name': {'type': 'string'},
                    'reference': {'type': 'string'}}, 'required': ['name']}}})
        if self.verify and self.tools.policy.capabilities.test and (allowed_names is None or 'verify' in allowed_names):
            schemas.append({'type': 'function', 'function': {'name': 'verify',
                'description': 'Run project-configured tests and quality gates. No speculative commands or installations.',
                'parameters': {'type': 'object', 'properties': {}}}})
        return schemas

    def _validate_call(self, name: str, arguments: Any,
                       allowed_schemas: list[dict[str, Any]] | None,
                       argument_error: str | None) -> dict[str, Any] | None:
        canonical = ALIASES.get(name, name)
        available = {item["function"]["name"]: item["function"]
                     for item in (allowed_schemas if allowed_schemas is not None else self.schemas())}
        if (canonical == "make_directory" and allowed_schemas is None
                and self.tools.policy.capabilities.write and "write" in available):
            schema = {"parameters": {"type": "object", "properties": {"path": {"type": "string"}},
                                     "required": ["path"]}}
        else:
            schema = available.get(canonical)
        missing, invalid = [], []
        if argument_error or not isinstance(arguments, dict):
            invalid.append("arguments")
        elif schema is None:
            invalid.append("tool")
        else:
            missing, invalid = _argument_issues(arguments, schema.get("parameters", {}))
            if canonical == "edit" and isinstance(arguments.get("edits"), list) and not arguments["edits"]:
                invalid.append("edits")
            if canonical == "edit" and isinstance(arguments.get("edits"), list):
                for index, item in enumerate(arguments["edits"][:32]):
                    if isinstance(item, dict) and isinstance(item.get("old"), str) and not item["old"]:
                        invalid.append(f"edits[{index}].old")
            if canonical in {"bash", "git"} and isinstance(arguments.get("argv"), list) and not arguments["argv"]:
                invalid.append("argv")
            if "path" in arguments and isinstance(arguments["path"], str):
                path = arguments["path"]
                unsafe = (not path.strip() or "\x00" in path or Path(path).is_absolute()
                          or PureWindowsPath(path).is_absolute() or ".." in Path(path).parts
                          or (canonical in {"write", "append", "edit", "make_directory"}
                              and path in {".", "./"}))
                if not unsafe:
                    try:
                        self.tools._path(path)
                    except (PermissionError, ValueError, OSError):
                        unsafe = True
                if unsafe:
                    invalid.append("path")
        if not missing and not invalid:
            return None
        # Preserve direct-call permission semantics for existing callers; model
        # calls receive a bounded diagnostic with no private path values.
        if allowed_schemas is None and "path" in invalid:
            raise PermissionError("invalid or disallowed workspace-relative path")
        return {
            "error_code": "INVALID_TOOL_ARGUMENTS",
            "error": "Arguments do not match the granted tool schema; no operation was executed.",
            "tool": canonical if canonical in available or schema is not None else "<unavailable>",
            "missing_required": sorted(set(missing))[:8],
            "invalid_fields": sorted(set(invalid))[:8],
            "retryable": bool(schema is not None and "path" not in invalid and "tool" not in invalid),
            "example": EXAMPLES.get(canonical, {}),
        }

    def execute(self, name: str, arguments: dict[str, Any], *,
                allowed_schemas: list[dict[str, Any]] | None = None,
                argument_error: str | None = None) -> dict[str, Any]:
        if name == "verify" and (not self.tools.policy.capabilities.test or not callable(self.verify)):
            raise PermissionError("verification capability unavailable")
        if name == "make_directory" and not self.tools.policy.capabilities.write:
            raise PermissionError("tool capability denied: make_directory")
        canonical = ALIASES.get(name, name)
        if canonical not in {"verify", "load_skill", "make_directory"} and not self.tools.policy.allows(canonical):
            raise PermissionError(f"tool capability denied: {canonical}")
        if name == "replace_in_file" and isinstance(arguments, dict):
            arguments = {"path": arguments.get("path", ""), "edits": [{
                "old": arguments.get("old_text", arguments.get("old", "")),
                "new": arguments.get("new_text", arguments.get("new", "")),
            }]}
        diagnostic = self._validate_call(name, arguments, allowed_schemas, argument_error)
        if diagnostic is not None:
            return diagnostic
        if name == 'verify':
            if not self.tools.policy.capabilities.test or not callable(self.verify):
                raise PermissionError('verification capability unavailable')
            report = self.verify()
            # Full evidence remains in the session/events; only actionable facts
            # enter model context, not four copies of screenshots/DOM metadata.
            compact = {key: report.get(key) for key in ('verdict', 'sequence', 'changed_paths')}
            compact['checks'] = [{'name': item['name'], 'verdict': item['verdict'],
                                  'errors': item.get('errors', [])[:16]} for item in report.get('checks', [])]
            if report.get('verdict') == 'FAIL':
                compact['error'] = 'Repair these concrete failures; preserve existing working navigation targets.'
            else:
                compact['instruction'] = 'Checks passed. Do not run verify again unless files change; finish remaining objective or return final.'
            return compact
        if name == 'load_skill' and self.load_skill:
            return self.load_skill(**arguments)
        # Accept persisted 4.x tool calls during session migration; new schemas
        # advertise only the compact 5.x names.
        if name == "make_directory":
            return self.tools.make_directory(**arguments)
        name = canonical
        if not self.tools.policy.allows(name):
            raise PermissionError(f"tool capability denied: {name}")
        # v4.1.3 model-tool boundary: a fully parsed write/append whose
        # content exceeds the advertised chunk size is rejected BEFORE any
        # filesystem mutation. Low-level CodingTools stay unbounded for
        # internal Python callers and fixtures.
        if name in {"write", "append"}:
            content = arguments.get("content", "")
            if isinstance(content, str) and len(content) > self.max_write_chars:
                return {
                    "error": (
                        "CONTENT_TOO_LARGE: model write chunk exceeds "
                        f"{self.max_write_chars} characters "
                        f"(actual {len(content)})."
                    ),
                    "error_code": "CONTENT_TOO_LARGE",
                    "retryable": False,
                    "path": str(arguments.get("path", "?")),
                    "max_chars": self.max_write_chars,
                    "actual_chars": len(content),
                    "instruction": (
                        "CONTENT_TOO_LARGE. Maximum model write chunk: "
                        f"{self.max_write_chars} characters. Create a smaller "
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
                return {'cached': True, 'path': cached.get('path'),
                        'summary': 'Unchanged evidence already read in this session. Reuse previous result.',
                        'content': str(cached.get('content', ''))[:200]}
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
        value = json.dumps(redact_data(result), ensure_ascii=False, separators=(",", ":"))
        if len(value) <= limit:
            return value
        return value[:limit] + '\n{"truncated":true,"hint":"Use a narrower read, grep, or line range."}'
