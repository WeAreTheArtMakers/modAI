from __future__ import annotations

from collections import deque
from typing import Any, Iterable

from .base import ModelResponse


class ScriptedRuntime:
    """Deterministic runtime used by the harness acceptance suite."""

    provider = "fake"
    model = "scripted"
    supports_native_tools = True

    def __init__(self, responses: Iterable[ModelResponse]) -> None:
        self.responses = deque(responses)
        self.requests: list[dict[str, Any]] = []

    def generate(self, messages, tools, *, on_text=None) -> ModelResponse:
        self.requests.append({"messages": list(messages), "tools": list(tools)})
        if not self.responses:
            raise RuntimeError("ScriptedRuntime response queue is empty")
        response = self.responses.popleft()
        if on_text and response.content:
            on_text(response.content)
        return response
