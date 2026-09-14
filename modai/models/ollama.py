from __future__ import annotations

import json
import uuid
from collections.abc import Iterable, Mapping
from typing import Any

from .base import ModelResponse, ToolCall, Usage


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


class OllamaRuntime:
    """Capability-based Ollama adapter; it never depends on a concrete client class."""

    provider = "local"
    supports_native_tools = True

    def __init__(self, client: Any, model: str, *, options: dict[str, Any] | None = None,
                 keep_alive: str = "5m", stream: bool = True) -> None:
        if not callable(getattr(client, "chat", None)):
            raise TypeError("Model client must provide chat(**kwargs)")
        self.client = client
        self.model = model
        self.options = dict(options or {})
        self.keep_alive = keep_alive
        self.stream = stream

    def _normalize(self, raw: Any) -> ModelResponse:
        message = _value(raw, "message", {}) or {}
        calls: list[ToolCall] = []
        for raw_call in _value(message, "tool_calls", []) or []:
            fn = _value(raw_call, "function", {}) or {}
            calls.append(ToolCall(
                str(_value(raw_call, "id", "") or uuid.uuid4().hex),
                str(_value(fn, "name", "")),
                _arguments(_value(fn, "arguments", {})),
            ))
        reason = str(_value(raw, "done_reason", _value(raw, "stop_reason", "stop")) or "stop")
        return ModelResponse(
            content=str(_value(message, "content", "") or ""),
            tool_calls=calls,
            usage=Usage(int(_value(raw, "prompt_eval_count", 0) or 0),
                        int(_value(raw, "eval_count", 0) or 0)),
            stop_reason=reason,
            truncated=reason in {"length", "max_tokens"},
        )

    def generate(self, messages, tools, *, on_text=None) -> ModelResponse:
        kwargs = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
            "options": self.options,
            "keep_alive": self.keep_alive,
        }
        try:
            raw = self.client.chat(**kwargs, **({"stream": True} if self.stream else {}))
        except Exception as exc:
            # Compatibility path for older/local servers that reject native tool
            # schemas. The harness still validates the decoded call normally.
            if not tools or not any(word in str(exc).casefold() for word in ("tool", "schema", "function")):
                raise
            self.supports_native_tools = False
            fallback = list(messages)
            fallback.append({"role": "system", "content": (
                "Native tools are unavailable. For one tool call only, return strict JSON "
                '{"tool":"name","args":{...}}. Available schemas: ' + json.dumps(tools, ensure_ascii=False)
            )})
            raw = self.client.chat(model=self.model, messages=fallback, options=self.options,
                                   keep_alive=self.keep_alive)
        if not self.stream or isinstance(raw, Mapping) or not isinstance(raw, Iterable):
            return self._normalize(raw)
        content: list[str] = []
        calls: list[ToolCall] = []
        usage = Usage()
        reason = "stop"
        for chunk in raw:
            response = self._normalize(chunk)
            if response.content:
                content.append(response.content)
                if on_text:
                    on_text(response.content)
            calls.extend(response.tool_calls)
            if response.usage.input_tokens:
                usage.input_tokens = response.usage.input_tokens
            if response.usage.output_tokens:
                usage.output_tokens = response.usage.output_tokens
            reason = response.stop_reason or reason
        return ModelResponse("".join(content), calls, usage, reason,
                             reason in {"length", "max_tokens"})
