from __future__ import annotations

from pathlib import Path
from typing import Any

from modai.models.base import ModelRuntime
from modai.core.evidence import SharedEvidenceCache
from modai.tools.coding import CodingTools
from modai.tools.policy import Capabilities, ToolPolicy
from modai.tools.registry import ToolRegistry


class ReadOnlyDelegate:
    """A small, bounded evidence-gathering loop; it can never mutate the project."""

    def __init__(self, runtime: ModelRuntime, workspace: Path, log_dir: Path,
                 evidence: SharedEvidenceCache, network_enabled: bool = False,
                 max_turns: int = 4) -> None:
        self.runtime = runtime
        self.registry = ToolRegistry(CodingTools(
            workspace, ToolPolicy(Capabilities(read=True, write=False, test=False,
                                               network=network_enabled)), log_dir,
        ), evidence=evidence)
        self.max_turns = max_turns

    def run(self, task: str, focus: str = "") -> dict[str, Any]:
        # A cloud delegate receives only the explicitly consented public task,
        # not filesystem contents, test logs or private project instructions.
        if self.runtime.provider not in {'local', 'fake'}:
            from providers import contains_obvious_secret
            if contains_obvious_secret(task + '\n' + focus):
                raise PermissionError('Cloud delegation rejected: task contains a secret')
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": (
                "You are a bounded read-only delegate. Gather only the evidence requested. "
                "Do not propose broad rewrites, do not mutate files, and return a concise evidence memo."
            )},
            {"role": "user", "content": f"Task: {task}\nFocus: {focus}"},
        ]
        tool_count = 0
        input_tokens = 0
        output_tokens = 0
        for _turn in range(self.max_turns):
            schemas = self.registry.schemas()
            if self.runtime.provider not in {'local', 'fake'}:
                schemas = [s for s in schemas if s['function']['name'] in {'web_search', 'fetch_url'}]
            response = self.runtime.generate(messages, schemas)
            if response.truncated or (not response.content.strip() and not response.tool_calls):
                raise RuntimeError('Delegate produced no complete visible response; no evidence memo accepted')
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens
            assistant: dict[str, Any] = {"role": "assistant", "content": response.content}
            if response.tool_calls:
                assistant["tool_calls"] = [{"id": call.id, "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments}} for call in response.tool_calls]
            messages.append(assistant)
            if not response.tool_calls:
                return {"memo": response.content.strip(), "tool_calls": tool_count, "bounded": True,
                        "_usage": {"provider": self.runtime.provider, "input_tokens": input_tokens,
                                   "output_tokens": output_tokens}}
            for call in response.tool_calls:
                try:
                    if call.name not in {s['function']['name'] for s in schemas}:
                        raise PermissionError('Delegate called a tool outside granted schemas')
                    result = self.registry.execute(call.name, call.arguments)
                except Exception as exc:
                    result = {"error": f"{type(exc).__name__}: {exc}"}
                messages.append({"role": "tool", "tool_call_id": call.id, "name": call.name,
                                 "content": self.registry.model_result(result)})
                tool_count += 1
        return {"memo": "Delegate turn limit reached; use the evidence in its tool results.",
                "tool_calls": tool_count, "bounded": True,
                "_usage": {"provider": self.runtime.provider, "input_tokens": input_tokens,
                           "output_tokens": output_tokens}}
